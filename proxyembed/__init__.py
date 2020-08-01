"""Auto-unwrapping d.py embeds for use with Red,
which respect Red's ctx.embed_requested()"""

import logging
import re
from collections import defaultdict
from typing import NoReturn

import discord
from babel.dates import format_datetime
from redbot.core.commands import Context
from redbot.core.i18n import get_babel_locale
from redbot.core.utils import chat_formatting as CF

__all__ = ["ProxyEmbed"]
__author__ = "Zephyrkul"
__version__ = "0.0.2"

LOG = logging.getLogger("red.fluffy.proxyembed")
LINK_MD = re.compile(r"\[([^\]]+)\]\(([^\)]+)\)")


def _links(string: str) -> str:
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


class ProxyEmbed(discord.Embed):
    def __new__(cls, *args, **kwargs):
        # d.py likes to call __new__ without __init__
        self = super().__new__(cls)
        self._overwrites = _OverwritesEmbed()
        return self

    @property
    def overwrites(self):
        return self._overwrites

    @classmethod
    def _get(cls, obj, attr):
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
            LOG.debug("Returning overwritten value %r", overwrite)
            return overwrite
        if obj is not self.Empty:
            return obj
        return self.Empty

    async def send_to(self, ctx: Context, content: str = None) -> None:
        if await ctx.embed_requested():
            return await ctx.send(content=content, embed=self)
        content = str(content) if content is not None else None
        if content:
            unwrapped = [content, ""]
        else:
            unwrapped = []
        title = self._("title")
        if title:
            unwrapped.append(CF.bold(title))
        url = self._("url")
        if url:
            unwrapped.append(f"> <{url}>")
        name = self._("author.name")
        if name:
            unwrapped.append(CF.italics(name))
        url = self._("author.url")
        if url:
            unwrapped.append(f"> <{url}>")
        if unwrapped and unwrapped[-1]:
            unwrapped.append("")
        url = self._("thumbnail.url")
        if url and not url.startswith("attachment://"):
            unwrapped.append(f"<{url}>")
        description = self._("description")
        if description:
            unwrapped.extend(f"> {line}" for line in description.split("\n"))
        if unwrapped and unwrapped[-1]:
            unwrapped.append("")
        for i in range(len(getattr(self, "_fields", []))):
            inline, name, value = (
                self._("_fields", i, "inline"),
                self._("_fields", i, "name"),
                self._("_fields", i, "value"),
            )
            LOG.debug("index: %r, inline: %r, name: %r, value: %r", i, inline, name, value)
            name = f"**{name}**"
            if not inline or len(name) + len(value) > 78 or "\n" in name or "\n" in value:
                unwrapped.append(name)
                unwrapped.extend(f"> {line}" for line in value.split("\n"))
            else:
                unwrapped.append(f"{name} | {value}")
        if unwrapped and unwrapped[-1]:
            unwrapped.append("")
        url = self._("image.url")
        if url and not url.startswith("attachment://"):
            unwrapped.append(f"<{url}>")
        text, timestamp = self._("footer.text"), self._("timestamp")
        if text and timestamp:
            ftimestamp = format_datetime(timestamp, locale=get_babel_locale())
            unwrapped.append(f"{text} • {ftimestamp}")
        elif text:
            unwrapped.append(text)
        elif timestamp:
            ftimestamp = format_datetime(timestamp, locale=get_babel_locale())
            unwrapped.append(f"{ftimestamp}")

        route = discord.http.Route(
            "POST", "/channels/{channel_id}/messages", channel_id=ctx.channel.id
        )
        pages = CF.pagify(_links("\n".join(map(str, unwrapped))), shorten_by=0)
        for page in pages:
            await ctx.bot.http.request(
                route, json={"content": page, "allowed_mentions": {"parse": []}}
            )
