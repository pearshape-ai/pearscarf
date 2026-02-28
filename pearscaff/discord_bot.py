from __future__ import annotations

import asyncio
import threading

import discord

from pearscaff import db
from pearscaff.agents.runner import AgentRunner
from pearscaff.agents.worker import create_worker_agent
from pearscaff.bus import MessageBus
from pearscaff.config import DISCORD_BOT_TOKEN
from pearscaff.experts.gmail import create_gmail_expert_for_runner


class PearscaffBot(discord.Client):
    def __init__(self, bus: MessageBus) -> None:
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(intents=intents)
        self._bus = bus
        self._poll_task: asyncio.Task | None = None

    async def on_ready(self) -> None:
        print(f"Logged in as {self.user}")
        # Start polling for messages addressed to human
        self._poll_task = asyncio.create_task(self._poll_responses())

    async def on_message(self, message: discord.Message) -> None:
        if message.author == self.user:
            return
        if not self.user:
            return

        # Respond to DMs or mentions
        is_dm = isinstance(message.channel, discord.DMChannel)
        is_mention = self.user.mentioned_in(message)

        if not is_dm and not is_mention:
            # Check if this is a reply in a thread we created
            if not isinstance(message.channel, discord.Thread):
                return

        # Strip the bot mention from the message text
        content = message.content
        if is_mention:
            content = content.replace(f"<@{self.user.id}>", "").strip()

        if not content:
            return

        # Determine session: if in a thread, look up existing session
        if isinstance(message.channel, discord.Thread):
            session_id = db.get_session_by_thread(message.channel.id)
            if not session_id:
                # Thread not tracked, create a session for it
                session_id = self._bus.create_session("human", content[:80])
                db.save_thread_mapping(
                    session_id, message.channel.id, message.channel.parent_id or 0
                )
        else:
            # New message in a main channel — create session + thread
            session_id = self._bus.create_session("human", content[:80])

            thread = await message.create_thread(
                name=content[:100], auto_archive_duration=1440
            )
            db.save_thread_mapping(session_id, thread.id, message.channel.id)

            # Send to worker via bus
            self._bus.send(
                session_id=session_id,
                from_agent="human",
                to_agent="worker",
                content=content,
                reasoning="Human message from Discord",
            )
            return

        # In a thread — send to worker
        self._bus.send(
            session_id=session_id,
            from_agent="human",
            to_agent="worker",
            content=content,
            reasoning="Human message from Discord thread",
        )

    async def _poll_responses(self) -> None:
        """Poll for messages addressed to human and post to correct Discord thread."""
        while True:
            try:
                messages = await asyncio.get_running_loop().run_in_executor(
                    None, self._bus.poll, "human"
                )
                for msg in messages:
                    session_id = msg["session_id"]
                    content = msg["content"]
                    from_agent = msg["from_agent"]

                    thread_id = db.get_thread_by_session(session_id)
                    if thread_id:
                        thread = self.get_channel(thread_id)
                        if thread:
                            text = f"**{from_agent}**: {content}"
                            for i in range(0, len(text), 2000):
                                await thread.send(text[i : i + 2000])
                    else:
                        # Expert-initiated session with no thread yet
                        # Create a thread in the first text channel we can find
                        for guild in self.guilds:
                            for channel in guild.text_channels:
                                if channel.permissions_for(guild.me).create_public_threads:
                                    summary = msg.get("reasoning", content[:80])
                                    thread = await channel.create_thread(
                                        name=f"{from_agent}: {summary[:90]}",
                                        auto_archive_duration=1440,
                                        type=discord.ChannelType.public_thread,
                                    )
                                    db.save_thread_mapping(
                                        session_id, thread.id, channel.id
                                    )
                                    text = f"**{from_agent}**: {content}"
                                    for i in range(0, len(text), 2000):
                                        await thread.send(text[i : i + 2000])
                                    break
                            break
            except Exception as exc:
                print(f"Poll error: {exc}")
            await asyncio.sleep(1)


def run_bot() -> None:
    if not DISCORD_BOT_TOKEN:
        raise SystemExit("DISCORD_BOT_TOKEN is not set.")

    bus = MessageBus()

    # Start Gmail expert runner
    gmail_factory, gmail_manager = create_gmail_expert_for_runner()
    gmail_runner = AgentRunner("gmail_expert", gmail_factory, bus)
    gmail_runner.start()
    print("Gmail expert started.")

    # Start Worker runner
    def worker_factory(session_id: str):
        return create_worker_agent(bus=bus, session_id=session_id)

    worker_runner = AgentRunner("worker", worker_factory, bus)
    worker_runner.start()
    print("Worker agent started.")

    # Run Discord bot
    bot = PearscaffBot(bus)
    try:
        bot.run(DISCORD_BOT_TOKEN)
    finally:
        worker_runner.stop()
        gmail_runner.stop()
        gmail_manager.close()
