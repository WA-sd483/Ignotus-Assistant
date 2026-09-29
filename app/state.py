"""状态机：桌宠与助手的运行状态。"""
from enum import Enum


class State(Enum):
    IDLE = "idle"
    LISTENING = "listening"
    THINKING = "thinking"
    SPEAKING = "speaking"
    WORKING = "working"
