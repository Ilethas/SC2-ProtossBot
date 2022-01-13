import sc2
from sc2.ids.unit_typeid import UnitTypeId
from sc2.ids.ability_id import AbilityId
from sc2.position import Point2
import pysm
from typing import Callable, Optional
from unit_ai_data import UnitAiOrder, UnitAiOrderType, UnitAiData, UnitAiController


class GroupMovement(pysm.StateMachine):
    """
    Stan, wedle którego jednostka powinna przemieszczać się w kierunku swojego obecego celu. Bot wydaje jednostce
    rozkaz przemieszczenia się do celu, jeśli jeszcze nie przemieszcza się do tego miejsca oraz jest jest od niego
    w odległości większej niż 5.
    """
    def __init__(self, name, unit_ai_data: UnitAiData):
        super().__init__(name)
        self.ai_data: UnitAiData = unit_ai_data

    def update(self, state, event):
        unit = self.ai_data.bot.units.find_by_tag(self.ai_data.unit_tag)
        if unit is not None and self.ai_data.unit_ai_order is not None:
            if self.ai_data.unit_ai_order.order is not None:
                already_going = (unit.is_moving and isinstance(unit.order_target, Point2) and
                                 unit.order_target.is_same_as(self.ai_data.unit_ai_order.arguments["target"]))

                if (unit.position - self.ai_data.unit_ai_order.arguments["target"]).length > 5 and not already_going:
                    unit.move(self.ai_data.unit_ai_order.arguments["target"])

    def register_handlers(self):
        self.handlers = {
            "update": self.update
        }


class AttackBestTarget(pysm.StateMachine):
    """
    Stan, w którym jednostka wybiera spośród wszystkich jednostek wroga, które są w zasięgu wroga, tę jednostkę
    (lub budynek), która jest najbardziej ranna oraz jest w stanie atakować. Preferowane są te jednostki, które
    są w zasięgu ataku lub w bliskiej odległości.
    """
    def __init__(self, name, unit_ai_data: UnitAiData):
        super().__init__(name)
        self.ai_data: UnitAiData = unit_ai_data

    def update(self, state, event):
        unit = self.ai_data.bot.units.find_by_tag(self.ai_data.unit_tag)
        if unit is None:
            return False

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

    def register_handlers(self):
        self.handlers = {
            "update": self.update
        }


class AvoidInjury(pysm.StateMachine):
    """
    Stan, w którym jednostka ucieka, gdy zostanie zraniona (od ostatniego wywołania funkcji self.on_step() bota)
    oraz posiada odpowiednio małą liczbę punktów życia oraz tarczy. Po pewnym czasie, jednostka powinna powrócić
    do walki.

    Metoda *enter* inicjalizuje stan ucieczki, np. sprawdzając, czy w pobliżu wciąż czają się wrogowie oraz wybierając
    dogodne miejsce do wycofania się.

    Następnie, w metodzie *update*, śledzony jest upływ czasu oraz czy jednostka dotarła do ustalonego miejsca ucieczki.
    """
    def __init__(self, name, unit_ai_data: UnitAiData):
        super().__init__(name)
        self.ai_data:           UnitAiData  = unit_ai_data
        self.escape_location:   Point2      = Point2((0.0, 0.0))
        self.start_time:        float       = 0.0
        self.ready_to_act:      bool        = False

    def enter(self, state, event):
        self.ready_to_act = False
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

    def update(self, state, event):
        unit = self.ai_data.bot.units.find_by_tag(self.ai_data.unit_tag)
        if unit is None:
            return

        if unit.distance_to(self.escape_location) < 1.0:
            self.ready_to_act = True

        timeout_happened = self.ai_data.bot.time - self.start_time > self.ai_data.timeout_duration
        if timeout_happened:
            self.ready_to_act = True

    def register_handlers(self):
        self.handlers = {
            "update": self.update,
            "enter": self.enter
        }


class UnitHfsmController(UnitAiController):
    """
    Klasa realizująca zachowanie pojedynczej jednostki w armii bota. Każda jednostka ma swój własny "rozum" w postaci
    hierarchicznej maszyny stanów. Podczas gdy obiekt *ArmyBht* kontroluje grupę składającą się z wielu jednostek i np.
    rozkazuje całej grupie atakować jakieś miejsce, szczegóły takiego rozkazu, jak chociażby to, w jaki sposób atakować,
    jest determinowane przez samą maszynę stanów jednostki.

    AI jednostki przemieszcza się w stronę rozkazu wskazanego przez armię (Move, MoveAttack lub DefendLocation).
    W zależności od posiadanego rozkazu, jednostka przełącza się ze stanu *GroupMovement* do stanu *Fight*, w którym
    znajduje się w trybie walki. Np. dla rozkazu Move, jednostka ignoruje pobliskich przeciwników, ale jeśli rozkaz
    to MoveAttack i jednostka w stanie GroupMovement zobaczy przeciwnika, przejdzie w tryb walki. Z kolei dla rozkazu
    DefendLocation, jednostka ignoruje pobliskich przeciwników, chyba że znajduje się w odpowiedniej odległości od
    miejsca, które powinna chronić.

    W stanie *Fight* jednostka przełącza się pomiędzy stanami *AttackBestTarget* oraz *AvoidInjury*. Gdy jednostka
    posiada dużo punktów życia oraz tarczy, wybiera najlepszy cel do ataku i walczy. W przeciwnym wypadku, gdy jednostka
    otrzyma obrażenia, chwilowo wycofuje się, by pozwolić jednostkom przeciwnika skupić się na pozostałych towarzyszach.
    """
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
                                                                 unit_attacked=self.unit_attacked)

        self.root               = pysm.StateMachine("Unit controller")
        self.fight              = pysm.StateMachine("Fight")
        self.group_movement     = GroupMovement("Group movement", self.unit_ai_data)
        self.attack_best_target = AttackBestTarget("Attack best target", self.unit_ai_data)
        self.avoid_injury       = AvoidInjury("Avoid injury", self.unit_ai_data)

        self.root.add_state(self.group_movement, initial=True)
        self.root.add_state(self.fight)
        self.fight.add_state(self.attack_best_target, initial=True)
        self.fight.add_state(self.avoid_injury)

        self.root.add_transition(self.group_movement,       self.fight,                 events=["should fight"])
        self.root.add_transition(self.fight,                self.group_movement,        events=["should not fight"])
        self.fight.add_transition(self.attack_best_target,  self.avoid_injury,          events=["is in danger"])
        self.fight.add_transition(self.avoid_injury,        self.attack_best_target,    events=["is ready to act"])

        self.root.initialize()

    @property
    def state(self):
        return self.root.leaf_state.name

    def should_fight(self):
        unit = self.bot.units.find_by_tag(self.unit_tag)
        if unit is None:
            return False

        # W zależności od rozkazu jednostki, sprawdź czy jednostka powinna reagować na pobliskich przeciwników.
        if self.unit_ai_data.unit_ai_order is not None:
            if self.unit_ai_data.unit_ai_order.order == UnitAiOrderType.DefendLocation:
                if (unit.position - self.unit_ai_data.unit_ai_order.arguments["target"]).length > self.unit_ai_data.defend_range:
                    return False
            elif self.unit_ai_data.unit_ai_order.order == UnitAiOrderType.Move:
                return False

        visible_enemies = (self.bot.enemy_units + self.bot.enemy_structures).filter(
            lambda enemy: unit.distance_to(enemy) <= unit.sight_range and enemy.can_be_attacked
        )
        return len(visible_enemies) > 0

    def is_in_danger(self):
        unit = self.bot.units.find_by_tag(self.unit_tag)
        if unit is None:
            return False
        return (unit.health + unit.shield) / (unit.health_max + unit.shield_max) < self.unit_ai_data.low_health and self.unit_attacked(unit.tag)

    def update(self):
        if self.should_fight():
            self.root.dispatch(pysm.Event("should fight"))
        else:
            self.root.dispatch(pysm.Event("should not fight"))

        if self.is_in_danger():
            self.root.dispatch(pysm.Event("is in danger"))

        if self.avoid_injury.ready_to_act:
            self.root.dispatch(pysm.Event("is ready to act"))

        self.root.dispatch(pysm.Event("update"))

    @property
    def order(self) -> Optional[UnitAiOrder]:
        return self.unit_ai_data.unit_ai_order

    @order.setter
    def order(self, new_order: Optional[UnitAiOrder]):
        self.unit_ai_data.unit_ai_order = new_order
