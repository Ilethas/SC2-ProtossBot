from sc2 import run_game, maps, Race, Difficulty
from sc2.player import Bot, Computer
from protoss_bot import ProtossBot

if __name__ == "__main__":
    run_game(maps.get("EternalEmpireLE"), [
        Bot(Race.Protoss, ProtossBot()),
        Computer(Race.Protoss, Difficulty.Medium)
    ], realtime=True)
