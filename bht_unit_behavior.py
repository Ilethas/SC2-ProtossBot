import sc2
from sc2.ids.unit_typeid import UnitTypeId
from sc2.ids.ability_id import AbilityId
from sc2.position import Point2
import py_trees
from py_trees.composites import Sequence, Selector, Parallel
from py_trees.decorators import Inverter
from py_trees.idioms import eternal_guard
from py_trees.behaviour import Behaviour
from unit_ai_data import UnitAiOrderType, UnitAiOrder, UnitAiData, UnitAiController
from typing import Callable, Optional


# =========================
# ===== ZADANIE 2
# Uzupełnij węzły drzewa zachowań na podstawie hierarchicznej maszyny stanów z pliku hfsm_unit_behavior.py. Większość
# kodu powinna być bardzo podobna – możesz zatem skopiować odpowiednie fragmenty i dostosować je, np. zwracać statusy
# SUCCESS, FAILURE lub RUNNING w odpowiednich miejscach.

class ShouldFight(Behaviour):
    """
    Węzeł sprawdza, czy w zasięgu wzroku jednostki są wrogowie, których można zaatakować.
    """
    def __init__(self, name: str, unit_ai_data: UnitAiData):
        super().__init__(name)
        self.ai_data: UnitAiData = unit_ai_data

    def update(self):
        unit = self.ai_data.bot.units.find_by_tag(self.ai_data.unit_tag)
        if unit is None:
            return py_trees.common.Status.FAILURE

        # W zależności od rozkazu jednostki, sprawdź czy jednostka powinna reagować na pobliskich przeciwników.
        if self.ai_data.unit_ai_order is not None:
            if self.ai_data.unit_ai_order.order == UnitAiOrderType.DefendLocation:
                if (unit.position - self.ai_data.unit_ai_order.arguments["target"]).length > self.ai_data.defend_range:
                    return py_trees.common.Status.FAILURE
            elif self.ai_data.unit_ai_order.order == UnitAiOrderType.Move:
                return py_trees.common.Status.FAILURE

        visible_enemies = (self.ai_data.bot.enemy_units + self.ai_data.bot.enemy_structures).filter(
            lambda enemy: unit.distance_to(enemy) <= unit.sight_range and enemy.can_be_attacked
        )
        if len(visible_enemies) > 0:
            return py_trees.common.Status.SUCCESS
        return py_trees.common.Status.FAILURE


class GroupMovement(Behaviour):
    """
    Węzeł powinien rozkazywać jednostkom przemieszczać się w kierunku obecnego celu rozkazu, podobnie jak jest to
    zrealizowane w przypadku implementacji opartej na hierarchicznej maszynie stanów.
    """
    def __init__(self, name: str, unit_ai_data: UnitAiData):
        super().__init__(name)
        self.ai_data: UnitAiData = unit_ai_data

    def initialise(self):
        ...

    def update(self):
        unit = self.ai_data.bot.units.find_by_tag(self.ai_data.unit_tag)
        if unit is not None and self.ai_data.unit_ai_order is not None:
            if self.ai_data.unit_ai_order.order is not None:
                already_going = (unit.is_moving and isinstance(unit.order_target, Point2) and
                                 unit.order_target.is_same_as(self.ai_data.unit_ai_order.arguments["target"]))

                if (unit.position - self.ai_data.unit_ai_order.arguments["target"]).length > 5 and not already_going:
                    unit.move(self.ai_data.unit_ai_order.arguments["target"])
        return py_trees.common.Status.SUCCESS


class IsInDanger(Behaviour):
    """
    Węzeł sprawdza, czy w danym momencie jednostka powinna unikać walki.
    """
    def __init__(self, name: str, unit_ai_data: UnitAiData):
        super().__init__(name)
        self.ai_data: UnitAiData = unit_ai_data

    def initialise(self):
        ...

    def update(self):
        unit = self.ai_data.bot.units.find_by_tag(self.ai_data.unit_tag)
        if unit is None:
            return py_trees.common.Status.FAILURE
        if (unit.health + unit.shield) / (unit.health_max + unit.shield_max) < self.ai_data.low_health and self.ai_data.unit_attacked(unit.tag):
            return py_trees.common.Status.SUCCESS
        return py_trees.common.Status.FAILURE


class AvoidInjury(Behaviour):
    """
    Węzeł odpowiedzialny za unikanie walki w chwili, gdy jest zagrożona.
    """
    def __init__(self, name: str, unit_ai_data: UnitAiData):
        super().__init__(name)
        self.ai_data:           UnitAiData  = unit_ai_data
        self.escape_location:   Point2      = Point2((0.0, 0.0))
        self.start_time:        float       = 0.0

    def initialise(self):
        self.start_time = self.ai_data.bot.time
        unit = self.ai_data.bot.units.find_by_tag(self.ai_data.unit_tag)
        if unit is not None:
            # Zbierz jednostki, które mogą zagrozić naszej jednostce
            visible_enemies = (self.ai_data.bot.enemy_units + self.ai_data.bot.enemy_structures).filter(
                lambda enemy: unit.distance_to(enemy) <= unit.sight_range and enemy.can_be_attacked
            )

            # Jeśli takie jednostki istnieją, uciekaj (wykorzystując np. zdolność Blink, jeśli jest dostępna)
            if len(visible_enemies) > 0:
                direction = unit.position - visible_enemies.center
                if abs(direction) > 0:
                    self.escape_location = unit.position + direction
                    if unit.type_id == UnitTypeId.STALKER:
                        unit(AbilityId.EFFECT_BLINK_STALKER, self.escape_location)
                    unit.move(self.escape_location)

    def update(self):
        unit = self.ai_data.bot.units.find_by_tag(self.ai_data.unit_tag)
        if unit is None:
            return py_trees.common.Status.FAILURE

        if unit.distance_to(self.escape_location) < 1.0:
            return py_trees.common.Status.SUCCESS

        timeout_happened = self.ai_data.bot.time - self.start_time > self.ai_data.timeout_duration
        if timeout_happened:
            return py_trees.common.Status.SUCCESS
        return py_trees.common.Status.RUNNING


class AttackBestTarget(Behaviour):
    """
    Węzeł odpowiedzialny za wybór odpowiedniego celu do ataku oraz atakowanie.
    """
    def __init__(self, name: str, unit_ai_data: UnitAiData):
        super().__init__(name)
        self.ai_data:           UnitAiData  = unit_ai_data
        self.escape_location:   Point2      = Point2((0.0, 0.0))
        self.start_time:        float       = 0.0
        self.ready_to_act:      bool        = False

    def initialise(self):
        ...

    def update(self):
        unit = self.ai_data.bot.units.find_by_tag(self.ai_data.unit_tag)
        if unit is None:
            return py_trees.common.Status.FAILURE

        # Wybierz jednostki oraz budynki wroga, które jednostka widzi
        enemy_units = self.ai_data.bot.enemy_units.filter(
            lambda enemy: unit.distance_to(enemy) <= unit.sight_range and enemy.can_be_attacked
        )
        enemy_structures = self.ai_data.bot.enemy_structures.filter(
            lambda enemy: unit.distance_to(enemy) <= unit.sight_range
        )

        # Preferuj jednostki, które atakują oraz są blisko
        visible_enemies = enemy_units + enemy_structures.filter(lambda enemy: enemy.can_attack)
        visible_enemies.sort(key=lambda enemy: unit.distance_to(enemy))
        enemies_in_range = visible_enemies.in_attack_range_of(unit, bonus_distance=unit.sight_range * 0.15)

        enemies = visible_enemies
        if len(enemies_in_range) > 0:
            enemies = enemies_in_range

        # Wybierz jednostkę, która jest najbardziej ranna. Jeśli wśród niebezpiecznych jednostek nikogo nie udało się
        # znaleźć, zaatakuj inne, nie niebezpieczne cele.
        best_target = min(enemies,
                          key=lambda enemy: (enemy.health + enemy.shield) / (enemy.health_max + enemy.shield_max + self.ai_data.eps),
                          default=None)
        if best_target is None and enemy_structures.exists:
            best_target = enemy_structures.closest_to(unit)

        if best_target is not None:
            if not (unit.is_attacking and unit.order_target == best_target.tag):
                if unit.type_id == UnitTypeId.SENTRY:
                    unit(AbilityId.GUARDIANSHIELD_GUARDIANSHIELD)
                unit.attack(best_target)
        return py_trees.common.Status.SUCCESS


class UnitBhtController(UnitAiController):
    def construct_behavior_tree(self) -> Behaviour:
        """
        Metoda konstruująca drzewo zachowań ze zdefiniowanych wcześniej węzłów.

        Returns
        -------
        out : Behaviour
            instancja drzewa zachowań pozwalająca na sterowanie zachowaniem jednostki.
        """
        root = Selector(name="Unit behavior")

        movement_sequence   = Sequence(name="Group movement")
        should_fight        = ShouldFight(name="Should fight", unit_ai_data=self.unit_ai_data)
        should_not_fight    = Inverter(name="Should not fight", child=should_fight)
        group_movement      = GroupMovement("Group movement", unit_ai_data=self.unit_ai_data)
        movement_sequence.add_children([should_not_fight, group_movement])

        enemy_avoidance     = Sequence(name="Enemy avoidance")
        is_in_danger        = IsInDanger(name="Is in danger", unit_ai_data=self.unit_ai_data)
        avoid_injury        = AvoidInjury(name="Avoid injury", unit_ai_data=self.unit_ai_data)
        enemy_avoidance.add_children([is_in_danger, avoid_injury])

        attack_best_target  = AttackBestTarget(name="Attack best target", unit_ai_data=self.unit_ai_data)
        root.add_children([movement_sequence, enemy_avoidance, attack_best_target])
        return root

    def __init__(self,
                 unit_tag:      int,
                 bot:           sc2.BotAI,
                 unit_attacked: Callable[[int], bool]):
        self.unit_tag:      int                     = unit_tag
        self.bot:           sc2.BotAI               = bot
        self.unit_attacked: Callable[[int], bool]   = unit_attacked
        self.unit_ai_data:  UnitAiData              = UnitAiData(bot=bot,
                                                                 unit_tag=unit_tag,
                                                                 unit_ai_order=None,
                                                                 unit_attacked=unit_attacked)
        self.behavior_tree:     Behaviour           = self.construct_behavior_tree()

    def render_tree(self):
        # =========================
        # ===== ZADANIE 2
        # W tej metodzie dodaj rysowanie drzewa zachowań (podmień "..." na odpowiedni kod)
        ...

    def update(self):
        self.behavior_tree.tick_once()

    @property
    def order(self) -> Optional[UnitAiOrder]:
        return self.unit_ai_data.unit_ai_order

    @order.setter
    def order(self, new_order: Optional[UnitAiOrder]):
        self.unit_ai_data.unit_ai_order = new_order
