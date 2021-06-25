"""Auto-unwrapping d.py embeds for use with Red,
which respect Red's ctx.embed_requested()"""

import functools
import logging
import re
import warnings
from collections import defaultdict
from datetime import datetime
from types import SimpleNamespace
from typing import NoReturn, Optional, Union, cast, overload

import discord
from babel.dates import format_datetime
from redbot.core import commands
from redbot.core.bot import Red
from redbot.core.i18n import get_babel_locale
from redbot.core.utils.chat_formatting import bold, italics, quote

__all__ = ["ProxyEmbed", "EmptyOverwrite", "embed_requested"]
__author__ = "Zephyrkul"
__version__ = "0.1.0"

LOG = logging.getLogger("red.fluffy.proxyembed")
LINK_MD = re.compile(r'\[([^\]]+)\]\(([^\)]+)( "[^"]")?\)')
MM_RE = re.compile(r"@(everyone|here)")


def _reformat_links(string: str) -> str:
    return LINK_MD.sub(r"\1 (<\2>)", string)


class _OverwritesEmbed(discord.Embed):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._fields = defaultdict(
            lambda: defaultdict(lambda: self.Empty),
            {i: v for i, v in enumerate(getattr(self, "_fields", ()))},
        )

    @property
    def fields(self):
        return defaultdict(
            lambda: discord.embeds.EmbedProxy({}),
            {i: discord.embeds.EmbedProxy(v) for i, v in self._fields.items()},
        )

    def add_field(self, *args, **kwargs) -> NoReturn:
        raise NotImplementedError("This operation is unsupported for overwrites.")


EmptyOverwrite = ""


async def embed_requested(
    __dest: Union[discord.abc.Messageable, discord.Message, discord.PartialMessage],
    /,
    *,
    bot: None = None,
    command: commands.Command = None,
) -> bool:
    """
    Helper method to determine whether to send an embed to any arbitrary destination.
    """
    if bot is not None:
        warnings.warn("Passing 'bot' to 'embed_requested' is deprecated.", DeprecationWarning)
    # Note: This doesn't handle GroupChannel. Bots can't access GroupChannels.
    if method := getattr(__dest, "embed_requested", None):
        return await method()
    ns: SimpleNamespace
    client: Red
    if isinstance(__dest, discord.Message):
        client = __dest._state._get_client()  # type: ignore
        ns = SimpleNamespace(channel=__dest.channel, user=__dest.author, guild=__dest.guild)
    elif isinstance(__dest, discord.PartialMessage):
        client = __dest._state._get_client()  # type: ignore
        ns = SimpleNamespace(
            channel=__dest.channel,
            user=getattr(__dest.channel, "recipient", None),
            guild=__dest.guild,
        )
    else:
        channel = await __dest._get_channel()  # type: ignore
        client = channel._state._get_client()  # type: ignore
        if user := getattr(channel, "recipient", None):
            ns = SimpleNamespace(channel=channel, user=user, guild=None)
        elif guild := getattr(channel, "guild", None):
            # the actual user object here doesn't matter
            ns = SimpleNamespace(channel=channel, user=None, guild=guild)
        else:
            raise TypeError(f"Unknown destination type {__dest.__class__!r}")
    if ns.guild and not ns.channel.permissions_for(ns.guild.me).embed_links:
        return False
    return await client.embed_requested(ns.channel, ns.user, command=command)


class ProxyEmbed(discord.Embed):
    """Proxy object for a :class:`discord.Embed` object that unwraps itself into
    ``content`` automatically if the embed can't / shouldn't be sent.

    Extra Attributes
    ----------------
    overwrites: :class:`discord.Embed`
        A special Embed subclass to indicate what should change if
        this ProxyEmbed needs to unwrap into text.
        Ignored completely if this ProxyEmbed sends normally.
    EmptyOverwrite
        A sentinel value used by :attr:`overwrites` to send nothing
        if this ProxyEmbed unwraps into text.
        Ignored completely if this ProxyEmbed sends normally.

        (Impl. note: This is just the empty string. Use the attribute anyway in case that ever changes.)
    """

    # repeating __slots__ is a slight performance hit,
    # but to_dict requires doing so here
    __slots__ = ("_overwrites", *discord.Embed.__slots__)
    _overwrites: _OverwritesEmbed
    EmptyOverwrite = EmptyOverwrite

    def __new__(cls, *args, **kwargs):
        # d.py likes to call __new__ without __init__
        self = super().__new__(cls)
        self._overwrites = _OverwritesEmbed()
        return self

    @classmethod
    def from_embed(cls, embed: discord.Embed):
        return cls.from_dict(embed.to_dict())

    @property
    def overwrites(self):
        return self._overwrites

    @classmethod
    def __get(cls, obj, attr):
        if obj == EmptyOverwrite:
            return obj
        try:
            obj = getattr(obj, attr)
        except AttributeError:
            try:
                # pylint: disable=E1136
                obj = obj[int(attr)]
            except (ValueError, IndexError, KeyError, TypeError):
                try:
                    # pylint: disable=E1136
                    obj = obj[attr]
                except (IndexError, KeyError, TypeError):
                    return cls.Empty
        return obj

    # Return type is a lie. Actual return type is:
    # str | bool | int | discord.Colour | datetime.datetime | _EmptyEmbed
    def __unwrap_overwrite(self, *attrs) -> Optional[str]:
        if not attrs:
            raise TypeError
        attrs = ".".join(map(str, attrs))
        overwrite = self.overwrites
        obj = self
        for attr in attrs.split("."):
            if overwrite is not self.Empty:
                overwrite = self.__get(overwrite, attr)
            obj = self.__get(obj, attr)
        if overwrite is not self.Empty:
            LOG.debug(
                "Returning overwritten value %r for attr ProxyEmbed.%s",
                overwrite,
                attrs,
            )
            return overwrite  # type: ignore
        return obj  # type: ignore

    def to_dict(self):
        result = super().to_dict()
        result.pop("overwrites", None)
        return result

    @overload
    async def send_to(
        self,
        __dest: discord.Message,
        /,
        *,
        command: Optional[commands.Command] = None,
        **kwargs,
    ) -> None:
        ...

    @overload
    async def send_to(
        self,
        __dest: Union[discord.abc.Messageable, discord.PartialMessage],
        /,
        *,
        command: Optional[commands.Command] = None,
        **kwargs,
    ) -> discord.Message:
        ...

    async def send_to(
        self,
        __dest: Union[discord.abc.Messageable, discord.Message, discord.PartialMessage],
        /,
        *,
        command: Optional[commands.Command] = None,
        **kwargs,
    ) -> Optional[discord.Message]:
        """
        Sends this ProxyEmbed to the specified destination.

        If embeds can't / shouldn't be sent, this will unwrap this ProxyEmbed
        into pure text and send that instead.

        Note that this **does not** pagify large embeds for you.
        Use pagify on your own if you believe your embed may be too large.
        """
        if kwargs.pop("bot", None) is not None:  # this is no longer required
            LOG.debug("Unnecessary 'bot' argument passed to ProxyEmbed", stack_info=True)
        if kwargs.pop("embed", self) is not self:
            raise TypeError("send_to() got an unexpected kwarg 'embed'")
        if isinstance(__dest, (discord.Message, discord.PartialMessage)):
            send = functools.partial(__dest.edit, **kwargs)
        else:
            send = functools.partial(__dest.send, **kwargs)
        if await embed_requested(__dest, command=command):
            return await send(embed=self)
        _ = self.__unwrap_overwrite
        try:
            content = kwargs.pop("content")
        except KeyError:
            content = getattr(__dest, "content", None)
        content = str(content) if content is not None else None
        unwrapped = []
        if content:
            unwrapped.extend([content, ""])
        title = _("title")
        if title:
            unwrapped.append(bold(title))
        url = _("url")
        if url:
            unwrapped.append(f"> <{url}>")
        name = _("author.name")
        if name:
            unwrapped.append(italics(name))
        url = _("author.url")
        if url:
            unwrapped.append(f"<{url}>")
        if unwrapped and unwrapped[-1]:
            unwrapped.append("")
        url = _("thumbnail.url")
        if url and not url.startswith("attachment://"):
            unwrapped.append(f"<{url}>")
        description = _("description")
        if description:
            unwrapped.append(quote(description))
        if unwrapped and unwrapped[-1]:
            unwrapped.append("")
        for i in range(len(getattr(self, "_fields", []))):
            inline, name, value = (
                cast(bool, _("_fields", i, "inline")),
                _("_fields", i, "name"),
                _("_fields", i, "value"),
            )
            assert name and value
            LOG.debug("index: %r, inline: %r, name: %r, value: %r", i, inline, name, value)
            name = f"**{name}**"
            if not inline or len(name) + len(value) > 78 or "\n" in name or "\n" in value:
                unwrapped.append(name)
                unwrapped.append(quote(value))
            else:
                unwrapped.append(f"{name} | {value}")
        if unwrapped and unwrapped[-1]:
            unwrapped.append("")
        url = _("image.url")
        if url and not url.startswith("attachment://"):
            unwrapped.append(f"<{url}>")
        text, timestamp = _("footer.text"), cast(datetime, _("timestamp"))
        if text and timestamp:
            unwrapped.append(f"{text} • <t:{timestamp.timestamp():.0f}>")
        elif text:
            unwrapped.append(text)
        elif timestamp:
            ftimestamp = format_datetime(timestamp, format="long", locale=get_babel_locale())
            unwrapped.append(ftimestamp)

        mentions: Optional[discord.AllowedMentions]
        if mentions := kwargs.get("allowed_mentions", None):
            if not content or not MM_RE.search(content):
                mentions.everyone = False
            for attr in ("roles", "users"):
                # use == here in case it's default
                if getattr(mentions, attr) == True:
                    setattr(mentions, attr, False)
        else:
            if content and MM_RE.search(content):
                # don't specify everyone here, leave it default
                kwargs["allowed_mentions"] = discord.AllowedMentions(users=False, roles=False)
            else:
                kwargs["allowed_mentions"] = discord.AllowedMentions(
                    everyone=False, users=False, roles=False
                )

        return await send(content=_reformat_links("\n".join(unwrapped)))
