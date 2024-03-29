"""Auto-unwrapping d.py embeds for use with Red,
which respect Red's ctx.embed_requested()"""
from __future__ import annotations

import logging
import textwrap
import warnings
from collections import defaultdict
from datetime import datetime
from typing import TYPE_CHECKING, Any, Literal, NoReturn, Sequence, overload

import discord

if TYPE_CHECKING:
    from redbot.core import commands
    from redbot.core.bot import Red

try:
    import regex as re
except ImportError:
    import re

__all__ = ["ProxyEmbed", "EmptyOverwrite", "embed_requested"]
__author__ = "Zephyrkul"
__version__ = "1.0.0"

LOG = logging.getLogger("red.fluffy.proxyembed")
MM_RE = re.compile(r"@(everyone|here)")


def _quote(string: str) -> str:
    return textwrap.indent(string, "> ", lambda _: True)


class _OverwritesEmbed(discord.Embed):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._fields = defaultdict(
            lambda: defaultdict(lambda: None),
            {i: v for i, v in enumerate(getattr(self, "_fields", ()))},
        )

    @property
    def fields(self):
        return defaultdict(
            lambda: discord.embeds.EmbedProxy({}),
            {i: discord.embeds.EmbedProxy(v) for i, v in self._fields.items()},
        )

    def add_field(self, *args, **kwargs) -> NoReturn:
        raise NotImplementedError(
            "This operation is unsupported for overwrites; use set_field_at instead"
        )

    def insert_field_at(self, *args, **kwargs) -> NoReturn:
        raise NotImplementedError(
            "This operation is unsupported for overwrites; use set_field_at instead"
        )


EmptyOverwrite: Any = ""


async def embed_requested(
    __dest: discord.abc.Messageable | discord.Message | discord.PartialMessage,
    /,
    *,
    bot: None = None,
    command: commands.Command | None = None,
) -> bool:
    """
    Helper method to determine whether to send an embed to any arbitrary destination.
    """
    if bot is not None:
        warnings.warn("Passing 'bot' to 'embed_requested' is deprecated.", DeprecationWarning)
    # Note: This doesn't handle GroupChannel. Bots can't access GroupChannels.
    client: Red = __dest._state._get_client()  # type: ignore
    if isinstance(__dest, (discord.Message, discord.PartialMessage)):
        __dest = __dest.channel
    elif isinstance(__dest, discord.DMChannel):
        __dest = __dest.recipient  # type: ignore
    return await client.embed_requested(__dest, command=command)  # type: ignore


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

        Impl. note: This is just the empty string.
        Use the attribute anyway in case that ever changes.
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
                    return None
        return obj

    @overload
    def __unwrap_overwrite(
        self, _1: Literal["_fields"], _2: int, _3: Literal["inline"], /
    ) -> bool | None:
        ...

    @overload
    def __unwrap_overwrite(self, _1: Literal["_fields"], _2: int, _3: str, /) -> str | None:
        ...

    @overload
    def __unwrap_overwrite(self, _1: Literal["timestamp"], /) -> datetime | None:
        ...

    @overload
    def __unwrap_overwrite(self, _1: str, /, *attrs: str) -> str | None:
        ...

    # There are other overloads to consider, but they're not needed for now
    # Actual possible return types:
    # str | bool | int | discord.Colour | datetime.datetime | None
    def __unwrap_overwrite(self, *attrs):
        if not attrs:
            raise TypeError
        attrs = ".".join(map(str, attrs))
        overwrite = self.overwrites
        obj = self
        for attr in attrs.split("."):
            if overwrite is not None:
                overwrite = self.__get(overwrite, attr)
            obj = self.__get(obj, attr)
        if overwrite is not None:
            LOG.debug(
                "Returning overwritten value %r for attr ProxyEmbed.%s",
                overwrite,
                attrs,
            )
            return overwrite
        return obj

    def to_dict(self):
        result = super().to_dict()
        result.pop("overwrites", None)  # type: ignore
        return result

    @overload
    async def send_to(
        self,
        __dest: discord.Message | discord.PartialMessage,
        /,
        *,
        command: commands.Command | None = None,
        content: str | None = ...,
        attachments: Sequence[discord.Attachment | discord.File] = ...,
        suppress: bool = False,
        delete_after: float | None = None,
        allowed_mentions: discord.AllowedMentions | None = ...,
        view: discord.ui.View | None = ...,
    ) -> discord.Message:
        ...

    @overload
    async def send_to(
        self,
        __dest: discord.abc.Messageable,
        /,
        *,
        command: commands.Command | None = None,
        tts: bool = False,
        file: discord.File | None = None,
        stickers: Sequence[discord.GuildSticker | discord.StickerItem] | None = None,
        delete_after: float | None = None,
        nonce: str | int | None = None,
        allowed_mentions: discord.AllowedMentions | None = None,
        reference: discord.Message
        | discord.MessageReference
        | discord.PartialMessage
        | None = None,
        mention_author: bool | None = None,
        view: discord.ui.View | None = None,
        silent: bool = False,
    ) -> discord.Message:
        ...

    @overload
    async def send_to(
        self,
        __dest: discord.abc.Messageable,
        /,
        *,
        command: commands.Command | None = None,
        tts: bool = False,
        files: Sequence[discord.File] | None = None,
        stickers: Sequence[discord.GuildSticker | discord.StickerItem] | None = None,
        delete_after: float | None = None,
        nonce: str | int | None = None,
        allowed_mentions: discord.AllowedMentions | None = None,
        reference: discord.Message
        | discord.MessageReference
        | discord.PartialMessage
        | None = None,
        mention_author: bool | None = None,
        view: discord.ui.View | None = None,
        silent: bool = False,
    ) -> discord.Message:
        ...

    async def send_to(
        self,
        __dest: discord.abc.Messageable | discord.Message | discord.PartialMessage,
        /,
        *,
        command: commands.Command | None = None,
        **kwargs: Any,
    ) -> discord.Message:
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
            send = __dest.edit
        else:
            send = __dest.send
            kwargs["suppress_embeds"] = True
        if await embed_requested(__dest, command=command):
            kwargs.pop("suppress_embeds", None)
            return await send(embed=self, **kwargs)
        content = kwargs.pop("content", None)
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
        unwrapped = self.unwrap()
        if content is not None:
            unwrapped = f"{content}\n\n{unwrapped}"
        return await send(content=unwrapped, **kwargs)

    def unwrap(self) -> str:
        """
        Unwraps this ProxyEmbed into pure text.

        This is useful for embeds that can't be sent in Discord.
        """
        _ = self.__unwrap_overwrite
        emd = discord.utils.escape_markdown
        unwrapped: list[str] = []
        title = _("title")
        if title:
            unwrapped.append(f"**{emd(title)}**")
        url = _("url")
        if url:
            unwrapped.append(f"> {url}")
        name = _("author.name")
        if name:
            unwrapped.append(f"*{emd(name)}*")
        url = _("author.url")
        if url:
            unwrapped.append(f"<{url}>")
        if unwrapped and unwrapped[-1]:
            unwrapped.append("")
        url = _("thumbnail.url")
        if url and not url.startswith("attachment://"):
            unwrapped.append(f"{url}")
        description = _("description")
        if description:
            unwrapped.append(_quote(description))
        if unwrapped and unwrapped[-1]:
            unwrapped.append("")
        for i in range(len(getattr(self, "_fields", []))):
            inline, name, value = (
                _("_fields", i, "inline"),
                _("_fields", i, "name"),
                _("_fields", i, "value"),
            )
            assert name and value
            LOG.debug("index: %r, inline: %r, name: %r, value: %r", i, inline, name, value)
            name = f"**{emd(name)}**"
            if inline is False or len(name) + len(value) > 78 or "\n" in name or "\n" in value:
                unwrapped.append(name)
                unwrapped.append(_quote(value))
            else:
                unwrapped.append(f"{name} | {value}")
        if unwrapped and unwrapped[-1]:
            unwrapped.append("")
        url = _("image.url")
        if url and not url.startswith("attachment://"):
            unwrapped.append(f"{url}")
        text, timestamp = _("footer.text"), _("timestamp")
        if text and timestamp:
            unwrapped.append(f"{emd(text)} • <t:{timestamp.timestamp():.0f}>")
        elif text:
            unwrapped.append(emd(text))
        elif timestamp:
            unwrapped.append(f"<t:{timestamp.timestamp():.0f}>")
        return "\n".join(unwrapped)
