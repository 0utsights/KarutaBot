import asyncio
import discord

async def test():
    client = discord.Client(intents=discord.Intents.default())
    
    @client.event
    async def on_ready():
        print(f"Connected as {client.user}")
        await client.close()

    await client.start("NDA2OTE2NjU4MjM0NTIzNjQ5.GrGXER.rvDvlST48ZPON3ZeIY1hS4aHIDu9uU-gOFZRQU", bot=False)

asyncio.run(test())