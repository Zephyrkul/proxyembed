"""Auto-unwrapping d.py embeds for use with Red,
which respect Red's ctx.embed_requested()"""

import functools
import logging
import re
import textwrap
from collections import defaultdict
from types import SimpleNamespace
from typing import Any, Callable, Coroutine, NoReturn, Optional, Union

import discord
from babel.dates import format_datetime
from redbot.core.bot import Red
from redbot.core.i18n import get_babel_locale
from redbot.core.utils.chat_formatting import bold, italics

__all__ = ["ProxyEmbed", "EmptyOverwrite", "embed_requested"]
__author__ = "Zephyrkul"
__version__ = "0.0.4"

LOG = logging.getLogger("red.fluffy.proxyembed")
LINK_MD = re.compile(r"\[([^\]]+)\]\(([^\)]+)\)")
MM_RE = re.compile(r"@(everyone|here)")
quote = functools.partial(textwrap.indent, prefix="> ", predicate=lambda l: True)


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
            discord.embeds.EmbedProxy,
            {i: discord.embeds.EmbedProxy(v) for i, v in self._fields.items()},
        )

    def add_field(self, *args, **kwargs) -> NoReturn:
        raise NotImplementedError("This operation is unsupported for overwrites.")


EmptyOverwrite = ""


async def embed_requested(
    __dest: Union[discord.abc.Messageable, discord.Message],
    /,
    *,
    bot: Red = None,
) -> bool:
    """
    Helper method to determine whether to send an embed to any arbitrary destination.

    If neither ``ctx`` nor ``bot`` are passed, only Discord permissions are checked.
    """
    # Note: This doesn't handle GroupChannel. Bots can't access GroupChannels.
    if method := getattr(__dest, "embed_requested", None):
        return await method()
    ns: SimpleNamespace
    if isinstance(__dest, discord.Message):
        ns = SimpleNamespace(
            channel=__dest.channel, user=__dest.author, guild=__dest.guild
        )
    else:
        channel = await __dest._get_channel()
        if user := getattr(channel, "recipient", None):
            ns = SimpleNamespace(channel=channel, user=user, guild=None)
        elif guild := getattr(channel, "guild", None):
            # the actual user object here doesn't matter
            ns = SimpleNamespace(channel=channel, user=None, guild=guild)
        # And this is where I'd put my implementation for GroupChannel
        # if bots had them!
        else:
            raise TypeError(f"Unknown destination type {__dest.__class__!r}")
    if ns.guild and not ns.channel.permissions_for(ns.guild.me).embed_links:
        return False
    if not bot:
        LOG.warning("No bot kwarg provided; only checking permissions")
        return True
    return await bot.embed_requested(ns.channel, ns.user)


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

    __slots__ = ("_overwrites", *discord.Embed.__slots__)
    EmptyOverwrite = EmptyOverwrite

    def __new__(cls, *args, **kwargs):
        # d.py likes to call __new__ without __init__
        self = super().__new__(cls)
        self._overwrites = _OverwritesEmbed()
        return self

    @classmethod
    def from_embed(cls, embed: discord.Embed):
        if isinstance(embed, cls):
            return embed
        return cls.from_dict(embed.to_dict())

    @property
    def overwrites(self):
        return self._overwrites

    @classmethod
    def _get(cls, obj, attr):
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

    def _(self, *attrs):
        attrs = ".".join(map(str, attrs))
        overwrite = self.overwrites
        obj = self
        for attr in attrs.split("."):
            if overwrite is not self.Empty:
                overwrite = self._get(overwrite, attr)
            obj = self._get(obj, attr)
        if overwrite is not self.Empty:
            LOG.debug(
                "Returning overwritten value %r for attr ProxyEmbed.%r",
                overwrite,
                attrs,
            )
            return overwrite
        if obj is not self.Empty:
            return obj
        return self.Empty

    def to_dict(self):
        result = super().to_dict()
        result.pop("overwrites", None)
        return result

    async def send_to(
        self,
        __dest: Union[discord.abc.Messageable, discord.Message],
        /,
        *,
        bot: Red = None,
        **kwargs,
    ) -> discord.Message:
        """
        Sends this ProxyEmbed to the specified destination.

        If embeds can't / shouldn't be sent, this will unwrap this ProxyEmbed
        into pure text and send that instead.

        Note that this **does not** pagify large embeds for you.
        Use pagify on your own if you believe your embed may be too large.
        """
        _ = self._
        if kwargs.pop("embed", self) is not self:
            raise TypeError("send_to() got an unexpected kwarg 'embed'")
        bot = bot or getattr(__dest, "bot", None)
        send: Callable[..., Coroutine[Any, Any, Optional[discord.Message]]]
        if isinstance(__dest, discord.Message):
            send = functools.partial(__dest.edit, **kwargs)
        else:
            send = functools.partial(__dest.send, **kwargs)
        if await embed_requested(__dest, bot=bot):
            if message := await send(embed=self):
                return message
            else:
                assert isinstance(__dest, discord.Message)
                return __dest
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
                _("_fields", i, "inline"),
                _("_fields", i, "name"),
                _("_fields", i, "value"),
            )
            LOG.debug(
                "index: %r, inline: %r, name: %r, value: %r", i, inline, name, value
            )
            name = f"**{name}**"
            if (
                not inline
                or len(name) + len(value) > 78
                or "\n" in name
                or "\n" in value
            ):
                unwrapped.append(name)
                unwrapped.append(quote(value))
            else:
                unwrapped.append(f"{name} | {value}")
        if unwrapped and unwrapped[-1]:
            unwrapped.append("")
        url = _("image.url")
        if url and not url.startswith("attachment://"):
            unwrapped.append(f"<{url}>")
        text, timestamp = _("footer.text"), _("timestamp")
        if text and timestamp:
            ftimestamp = format_datetime(
                timestamp, format="long", locale=get_babel_locale()
            )
            unwrapped.append(f"{text} • {ftimestamp}")
        elif text:
            unwrapped.append(text)
        elif timestamp:
            ftimestamp = format_datetime(
                timestamp, format="long", locale=get_babel_locale()
            )
            unwrapped.append(ftimestamp)

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
                kwargs["allowed_mentions"] = discord.AllowedMentions(
                    users=False, roles=False
                )
            else:
                kwargs["allowed_mentions"] = discord.AllowedMentions(
                    everyone=False, users=False, roles=False
                )

        if message := await send(content=_reformat_links("\n".join(unwrapped))):
            return message
        else:
            assert isinstance(__dest, discord.Message)
            return __dest
