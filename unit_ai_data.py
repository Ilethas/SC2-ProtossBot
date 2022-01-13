from enum import Enum
from typing import Any, Dict, Optional, Callable
from abc import abstractmethod, abstractproperty
import sc2


class UnitAiOrderType(Enum):
    """
    Oznacza typ rozkazu, który mogą wykonywać jednostki należące do armii bota.
    """
    Move = 0            # Idź do wskazanego miejsca nie zważając na nic.
    MoveAttack = 1      # Idź do wskazanego miejsca i wejdź w tryb walki, gdy napatoczą się przeciwnicy.
    DefendLocation = 2  # Idź do określonej lokacji oraz atakuj wrogie jednostki w jej pobliżu.


class UnitAiOrder:
    """
    Klasa łącząca w sobie typ rozkazu oraz argumenty, jakie rozkaz ten może mieć.
    """
    def __init__(self, order: UnitAiOrderType, **arguments: Any):
        """
        Tworzy rozkaz danego rodzaju dla AI danej jednostki bojowej z podanymi argumentami. Przykład użycia:
        unit_order = UnitAiOrder(order=UnitAiOrderType.DefendLocation, target=location_to_defend)

        Argumenty rozkazu określane są przez słownik *arguments*. Jeśli utworzony zostanie rozkaz w następujący sposób:
        unit_order = UnitAiOrder(order=order_type, arg1=value1, arg2=value2, arg3=value3)

        Utworzony zostanie rozkaz typu *order_type*, którego zmienna *arguments* będzie słownikiem o następującej
        postaci:
        arguments = {
            arg1: value1,
            arg2: value2,
            arg3: value3
        }

        Parameters
        ----------
        order : UnitAiOrderType
            rodzaj rozkazu, który powinna wykonywać jednostka według używanej maszyny stanów (lub drzewa zachowań).
        arguments : Any
            argumenty dotyczące rozkazu do wykonania.
        """
        self.order:     UnitAiOrderType = order
        self.arguments: Dict[str, Any]  = arguments


class UnitAiData:
    """
    Pomocnicza klasa przechowująca dane, które mogą być wykorzystane przez węzły drzewa zachowań lub stany
    hierarchicznej maszyny stanów poszczególnych jednostek. Użycie takiej dodatkowej klasy pozwala na większą
    modularyzację architektury – węzły nie muszą się przejmować implementacją klasy ProtossBot ani klas kontrolerów
    (*UnitHfsmController* lub *UnitBhtController*).
    """
    def __init__(self,
                 bot: sc2.BotAI,
                 unit_tag: int,
                 unit_ai_order: Optional[UnitAiOrder],
                 unit_attacked: Callable[[int], bool]):
        self.bot:               sc2.BotAI               = bot
        self.unit_tag:          int                     = unit_tag
        self.unit_ai_order:     Optional[UnitAiOrder]   = unit_ai_order
        self.unit_attacked:     Callable[[int], bool]   = unit_attacked
        self.defend_range:      float                   = 15.
        self.low_health:        float                   = 0.45
        self.timeout_duration:  float                   = 5.
        self.eps:               float                   = 0.0001


class UnitAiController:
    """
    Klasa bazowa dla klas *UnitHfsmController* oraz *UnitBhtController*. Definiuje wspólny interfejs kontrolera dla
    poszczególnych jednostek.
    """
    @abstractmethod
    def update(self):
        raise NotImplementedError("update() abstract method not implemented in UnitAiController subclass.")

    @property
    @abstractmethod
    def order(self) -> Optional[UnitAiOrder]:
        raise NotImplementedError("order() abstract property getter not implemented in UnitAiController subclass.")

    @order.setter
    @abstractmethod
    def order(self, val: Optional[UnitAiOrder]):
        raise NotImplementedError("order() abstract property setter not implemented in UnitAiController subclass.")
