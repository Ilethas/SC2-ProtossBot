import sc2
from sc2.position import Point2
from sc2.units import Units
from typing import List, Callable
import py_trees
from py_trees.composites import Sequence, Selector
from py_trees.idioms import eternal_guard
from py_trees.behaviour import Behaviour
from unit_ai_data import UnitAiOrderType, UnitAiOrder, UnitAiController
import numpy as np
import random


class Army:
    """
    Pomocnicza klasa gromadząca dane przydatne dla węzłów drzewa zachowań kontrolującego armię gracza.
    """
    def __init__(self, bot: sc2.BotAI, get_unit_ai: Callable[[int], UnitAiController]):
        self.bot:               sc2.BotAI   = bot
        self.units:             List[int]   = []
        self.army_cluster_size: float       = 3.
        self.enemy_strength:    float       = 0.
        self.get_unit_ai:       Callable[[int], UnitAiController] = get_unit_ai


class IsArmyStrongEnough(Behaviour):
    """
    Węzeł sprawdzający, czy armia bota jest dość silna, aby być w stanie walczyć z wrogiem. Siła armii jest obliczana
    na podstawie sumarycznej ilości punktów obrażeń zadawanych na sekundę (dps) przez wszystkie jednostki armii.
    Wartość ta porównywana jest z tą samą miarą wyliczaną na podstawie do tej pory widzianych jednostek przeciwnika.
    Węzeł kończy pracę ze statusem *SUCCESS*, jeśli armia bota ma przewagę oraz *FAILURE* w przeciwnym wypadku.
    """
    def __init__(self, name: str, army: Army):
        super().__init__(name)
        self.army: Army = army

    def get_army_strength(self) -> float:
        return sum(unit.ground_dps for unit in self.army.bot.units.tags_in(self.army.units))

    def update(self):
        if self.get_army_strength() * 1.25 >= self.army.enemy_strength:
            return py_trees.common.Status.SUCCESS
        else:
            return py_trees.common.Status.FAILURE


class AreEnemiesVisible(Behaviour):
    """
    Węzeł sprawdza, czy którakolwiek jednostka należąca do armii ma w swoim zasięgu wzroku jednostkę przeciwnika, którą
    widzi (tzn. nie jest np. zamaskowana lub zakopana). Jeśli tak, węzeł kończy pracę z sukcesem lub, w przeciwnym
    wypadku, z porażką.
    """
    def __init__(self, name: str, army: Army):
        super().__init__(name)
        self.army: Army = army

    def update(self):
        units = self.army.bot.units.tags_in(self.army.units)
        for unit in units:
            visible_enemies = (self.army.bot.enemy_units + self.army.bot.enemy_structures).filter(
                lambda enemy: enemy.distance_to(unit) <= unit.sight_range and enemy.can_be_attacked
            )
            if visible_enemies.exists:
                return py_trees.common.Status.SUCCESS
        return py_trees.common.Status.FAILURE


class SeekEnemies(Behaviour):
    """
    Węzeł odpowiedzialny za poszukiwanie jednostek lub budynków przeciwnika w lokacjach startowych, miejscach
    zawierających złoża minerałów lub gazu oraz lokacjach, w których widziano budynki przeciwnika, ale są zakryte mgłą
    wojny.

    Zanim węzeł jest uruchamiany po raz pierwszy, następuje jego inicjalizacja, w której generowana jest lista miejsc,
    które powinna odwiedzić armia w poszukiwaniu wrogiego gracza. Następnie, w każdym kolejnym uruchomieniu, armia
    odwiedza kolejne miejsca oraz zwraca status *RUNNING* – ponieważ zadanie szukania jest w trakcie wykonywania.

    Gdy wszystkie miejsca zostaną odwiedzone, węzeł kończy pracę ze statusem *SUCCESS*. Jeśli natomiast armia nie
    posiada żadnej jednostki (jest pusta), węzeł kończy ze statusem *FAILURE*.
    """
    def __init__(self, name: str, army: Army):
        super().__init__(name)
        self.army: Army = army
        self.locations_to_check: List[Point2] = []

    def initialise(self):
        # Znajdowanie miejsc zawierających surowce.
        expansions = self.army.bot.expansion_locations_list
        random.shuffle(expansions)

        # Znajdowanie miejsc, w których widziano budynki wroga.
        snapshot_buildings = self.army.bot.enemy_structures.filter(lambda enemy: enemy.is_snapshot)
        buildings_locations = [building.position for building in snapshot_buildings]

        self.locations_to_check = buildings_locations + self.army.bot.enemy_start_locations + expansions

    def update(self):
        # Weź wszystkie jednostki bota o tagach z przechowywanej listy.
        units = self.army.bot.units.tags_in(self.army.units)
        if units.empty:
            return py_trees.common.Status.FAILURE

        # Jeśli jednostki dotarły do docelowego miejsca, usuń je z listy miejsc do odwiedzenia oraz kontynuuj
        # eksplorację.
        if len(self.locations_to_check) > 0:
            if (units.center - self.locations_to_check[0]).length < 5:
                self.locations_to_check.pop(0)
        else:
            return py_trees.common.Status.SUCCESS

        # Każ jednostkom iść do pierwszego miejsca do odwiedzenia z listy miejsc do odwiedzenia. Jeśli jednostki są
        # zbyt od siebie oddalone, rozkaż im zbić się w bardziej zwartą grupę.
        mean_distance = np.mean([(unit.position - units.center).length for unit in units])
        for unit in units:
            unit_ai = self.army.get_unit_ai(unit.tag)
            if mean_distance < self.army.army_cluster_size:
                unit_ai.order = UnitAiOrder(UnitAiOrderType.Move, target=self.locations_to_check[0])
            else:
                unit_ai.order = UnitAiOrder(UnitAiOrderType.Move, target=units.center)
        return py_trees.common.Status.RUNNING


class StayInBase(Behaviour):
    """
    Węzeł rozkazujący jednostkom z armii bota powrót do bazy oraz atakowanie jednostek tylko, gdy już się w niej
    znajdują. Węzeł zawsze kończy pracę ze statusem *SUCCESS*.
    """
    def __init__(self, name: str, army: Army):
        super().__init__(name)
        self.army: Army = army

    def update(self):
        units = self.army.bot.units.tags_in(self.army.units)
        base_buildings = self.army.bot.structures.in_distance_between(self.army.bot.start_location, 0, 25)
        if base_buildings.empty:
            target_location = self.army.bot.start_location
        else:
            target_location = base_buildings.center

        for unit in units:
            unit_ai = self.army.get_unit_ai(unit.tag)
            unit_ai.order = UnitAiOrder(UnitAiOrderType.DefendLocation, target=target_location)
        return py_trees.common.Status.SUCCESS


class Attack(Behaviour):
    """
    Węzeł, którego zadaniem jest sprawdzenie, czy któraś z jednostek armii ma w zasięgu swojego wzroku (oraz widzi ją,
    czyli nie jest zakopana lub zamaskowana) przeciwnika. W takim wypadku, armia rozkazuje wszystkim jednostkom
    atakować jednostki znajdujące się w pobiżu zauważonego wroga. Węzeł zawsze kończy pracę ze statusem *SUCCESS*.
    """
    def __init__(self, name: str, army: Army):
        super().__init__(name)
        self.army: Army = army

    def update(self):
        units = self.army.bot.units.tags_in(self.army.units)
        for unit in units:
            visible_enemies = (self.army.bot.enemy_units + self.army.bot.enemy_structures).filter(
                lambda enemy: enemy.distance_to(unit) <= unit.sight_range and enemy.can_be_attacked
            )
            if visible_enemies.exists:
                for unit in units:
                    unit_ai = self.army.get_unit_ai(unit.tag)
                    unit_ai.order = UnitAiOrder(UnitAiOrderType.MoveAttack,
                                                target=visible_enemies.closest_to(units.center).position)
                return py_trees.common.Status.SUCCESS
        return py_trees.common.Status.SUCCESS


class ArmyBht:
    """
    Klasa realizująca zachowanie armii składającej się z wielu jednostek bojowych. Armia przechowuje pomocniczy obiekt
    typu *Army*, który zawiera informacje o kompozycji jednostek oraz inne dodatkowe dane. Klasa przechowuje także
    drzewo zachowań, które w oparciu o dane z obiektu Army może podejmować decyzje dla całej gromady jednostek.

    AI armii w obecnej formie poszukuje wrogów na mapie oraz, jeśli jest uważa, że jest dość silna, aby walczyć z
    wrogiem. Jeśli zobaczy przeciwników i stwierdza, że są słabsi, atakuje przeciwników całą grupą. W przeciwnym
    wypadku, wycofuje się do bazy. Po wycofaniu się, armia odczekuje chwilę zanim ponownie wyruszy do walki.

    Warto zwrócić uwagę na węzeł *seek_enemies*. Jest to węzeł, którego wykonanie zajmuje bardzo dużo czasu (zwraca
    wiele razy status *RUNNING*). Należy przerwać jego wykonywanie, gdyby okazało się, że przeciwnik posiada
    silniejszą armię (bo np. w innej części mapy zauważono dużą ilość silnych jednostek) Żeby to zrobić, użyto
    kombinacji węzłów tworzonej za pomocą metody *eternal guard*, co pozwala przerwać działanie węzła *seek_enemies*.
    """
    def construct_behavior_tree(self) -> Behaviour:
        """
        Metoda konstruująca drzewo zachowań ze zdefiniowanych wcześniej węzłów.

        Returns
        -------
        out : Behaviour
            instancja drzewa zachowań pozwalająca na sterowanie zachowaniem armii bota.
        """
        is_army_strong_enough = IsArmyStrongEnough(name="Is army strong enough?", army=self.army)
        are_enemies_visible = AreEnemiesVisible(name="Are enemies visible?", army=self.army)

        stay_in_base = StayInBase(name="Stay in base", army=self.army)
        seek_enemies = SeekEnemies(name="Seek enemies", army=self.army)

        attack_visible_enemies = Sequence(name="Attack visible enemies")
        attack = Attack(name="Attack", army=self.army)
        attack_visible_enemies.add_children([are_enemies_visible, attack])

        root = Selector(name="Army behavior")
        move_out = Selector(name="Move out")
        move_out.add_children([attack_visible_enemies, seek_enemies])
        move_out_guard = eternal_guard(name="Move out guard", subtree=move_out, conditions=[is_army_strong_enough])
        root.add_children([move_out_guard, stay_in_base])
        return root

    def __init__(self, bot:         sc2.BotAI,
                 get_unit_ai:       Callable[[int], UnitAiController],
                 delta_time:        Callable[[], float]):
        self.army:              Army                = Army(bot, get_unit_ai)
        self.delta_time:        Callable[[], float] = delta_time
        self.behavior_tree:     Behaviour           = self.construct_behavior_tree()
        self.forget_rate:       float               = 0.1

    def calculate_units_strength(self, units: Units) -> float:
        """
        Oblicza siłę grupy jednostek w oparciu o liczbę zadawanych obrażeń na sekundę (dps).

        Parameters
        ----------
        units : Units
            grupa jednostek, której siłę należy obliczyć.

        Returns
        -------
        out : float
            obliczona siła grupy jednostek.
        """
        return sum(unit.ground_dps for unit in units)

    def update(self):
        # Obliczaj siłę armii wroga w oparciu o posiadane przez niego jednostki (te które do tej pory zobaczono).
        # Z czasem siła przeciwnika zmniejsza się (aż do 0), tak aby armia, jeśli się wycofała, mogła za jakiś czas
        # jeszcze raz zaatakować.
        self.army.enemy_strength = max(0.0,
                                       self.army.enemy_strength - self.delta_time() * self.forget_rate,
                                       self.calculate_units_strength(self.army.bot.enemy_units))
        self.behavior_tree.tick_once()
