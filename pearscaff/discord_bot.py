from __future__ import annotations

import asyncio
import functools

import discord

from pearscaff.agent import Agent
from pearscaff.config import DISCORD_BOT_TOKEN
from pearscaff.tools import registry


class PearscaffBot(discord.Client):
    def __init__(self) -> None:
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(intents=intents)
        self._agents: dict[int, Agent] = {}

    def _get_agent(self, channel_id: int) -> Agent:
        if channel_id not in self._agents:
            self._agents[channel_id] = Agent(tool_registry=registry)
        return self._agents[channel_id]

    async def on_ready(self) -> None:
        print(f"Logged in as {self.user}")

    async def on_message(self, message: discord.Message) -> None:
        if message.author == self.user:
            return
        if not self.user:
            return

        # Respond to mentions or DMs
        is_dm = isinstance(message.channel, discord.DMChannel)
        is_mention = self.user.mentioned_in(message)

        if not is_dm and not is_mention:
            return

        # Strip the bot mention from the message text
        content = message.content
        if is_mention:
            content = content.replace(f"<@{self.user.id}>", "").strip()

        if not content:
            return

        async with message.channel.typing():
            agent = self._get_agent(message.channel.id)
            loop = asyncio.get_running_loop()
            response = await loop.run_in_executor(
                None, functools.partial(agent.run, content)
            )

        # Discord has a 2000 char limit per message
        for i in range(0, len(response), 2000):
            await message.channel.send(response[i : i + 2000])


def run_bot() -> None:
    if not DISCORD_BOT_TOKEN:
        raise SystemExit("DISCORD_BOT_TOKEN is not set.")
    registry.discover()
    bot = PearscaffBot()
    bot.run(DISCORD_BOT_TOKEN)
