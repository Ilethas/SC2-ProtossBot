import sc2
from sc2.ids.unit_typeid import UnitTypeId
from sc2.ids.ability_id import AbilityId
from sc2.ids.buff_id import BuffId
from sc2.unit import Unit
from sc2.units import UnitSelection, Units
from sc2.position import Point2, Point3
from typing import List, Optional, Dict, Union, cast
import random
from enum import Enum
from unit_ai_data import UnitAiController
from hfsm_unit_behavior import UnitHfsmController
from bht_unit_behavior import UnitBhtController
from army_bht import ArmyBht
import py_trees


class UnitAiType(Enum):
    HierarchicalStateMachine = 0
    BehaviorTree = 1


class ProtossBot(sc2.BotAI):
    def __init__(self):
        super().__init__()
        self.eps:                       float               = 0.0001

        # Określa ile ramek gry przypada na 1 sekundę.
        self.frames_per_second:         float               = 22.4

        # Słownik zawiera dane jednostek, które od ostatniego wywołania metody self.on_step() utraciły punkty życia lub
        # tarczy pod kluczami będącymi tagami tych jednostek. Lista self.damaged_units przechowuje tagi tych jednostek.
        self.damaged_units:             List[int]           = []
        self.remembered_friendly_units: Dict[int, Unit]     = {}

        # Drzewo zachowań sterujące logiką armii bota.
        self.army_bht:                  ArmyBht             = ArmyBht(self,
                                                                      get_unit_ai=self.get_unit_ai,
                                                                      delta_time=self.delta_time)

        # Słownik przechowujący maszynę stanów lub drzewo zachowań dla każdej jednostki bojowej. Kluczem są tagi
        # jednostek.
        self.unit_controllers:          Dict[int, UnitAiController]   = {}

        # Determinuje typ AI, który jest wykorzystany do sterowania jednostkami (drzewa zachowań lub hierarchiczne
        # maszyny stanów).
        self.unit_ai_type:              UnitAiType                      = UnitAiType.BehaviorTree

    def delta_time(self) -> float:
        """
        Zwraca czas pomiędzy kolejnymi wywołaniami metody self.on_step().

        Returns
        -------
        out : float
            wartość czasu.
        """
        return self._client.game_step / self.frames_per_second

    def get_unit_ai(self, unit_tag: int) -> Optional[UnitAiController]:
        """
        Zwraca maszynę stanów (obiekt klasy *UnitHfsmController*) dla jednostki o tagu *unit_tag*.
        Jeśli nie istnieje jednostka o podanym tagu, metoda zwraca None.

        Parameters
        ----------
        unit_tag : int
            tag jednostki, której maszyna stanów powinna być odnaleziona.

        Returns
        -------
        out : UnitAiController
            obiekt *UnitHfsmController* będący maszyną stanów używaną do sterowania zachowaniem jednostki,
            obiekt *UnitBhtController*, jeśli wykorzystywane są drzewa zachowań, lub None.
        """
        return self.unit_controllers.get(unit_tag)

    def remember_damaged_units(self):
        """
        Metoda służąca do zapamiętania w słowniku self.remembered_friendly_units wszystkie takie jednostki,
        które od ostatniego wywołania metody self.on_step() utraciły punkty życia lub tarczy. Słownik przechowuje
        dane jednostek w postaci obiektów Unit pod kluczami będącymi tagami tych jednostek.
        """
        self.damaged_units.clear()
        for unit in self.units:
            if unit.tag in self.remembered_friendly_units:
                old_health = self.remembered_friendly_units[unit.tag].health
                old_shield = self.remembered_friendly_units[unit.tag].shield

                if unit.health < old_health or unit.shield < old_shield:
                    self.damaged_units.append(unit.tag)
            self.remembered_friendly_units[unit.tag] = unit

    def is_unit_attacked(self, unit_tag: int) -> bool:
        """
        Zwraca True jeśli jednostka o tagu *unit_tag* utraciła punkty życia lub tarczy od ostatniego wywołania metody
        self.on_step(). W przeciwnym wypadku (lub jeśli jednostka o podanym tagu nie istnieje), zwracana jest wartość
        False.

        Parameters
        ----------
        unit_tag : int
            tag jednostki do sprawdzenia.

        Returns
        -------
        out : bool
            wartość sprawdzenia opisanego wyżej.
        """
        return unit_tag in self.damaged_units

    def is_less_than(self, unit: UnitTypeId, count: int) -> bool:
        """
        Zwraca True, gdy liczba jednostek lub budynków podanego rodzaju, którą posiada gracz (lub jednostek w trakcie
        budowy, albo budynków, które dopiero zostaną zbudowane przez robotnika z rozkazem budowy takiej budowli) jest
        mniejsza niż podana liczba.

        Parameters
        ----------
        unit : UnitTypeId
            enumerator oznaczający rodzaj jednostki lub budynku, którego dotyczy test.
        count : int
            podana liczba jednostek lub budynków

        Returns
        -------
        out : bool
            wartość opisanego powyżej testu.
        """
        return (self.units(unit) + self.structures(unit)).ready.amount + self.already_pending(unit) < count

    def can_train(self, unit: UnitTypeId, max_amount: int = 200) -> bool:
        """
        Zwraca True, gdy liczba jednostek lub budynków danego typu jest mniejsza niż *max_amount* oraz gracz posiada
        dość surowców, aby zbudować tę jednostkę/budynek, a także, w przypadku jednostek, posiada odpowiednią ilość
        zaopatrzenia do jej wyszkolenia.

        Parameters
        ----------
        unit : UnitTypeId
            rodzaj jednostki lub budynku, którego dotyczy test.
        max_amount : int
            opcjonalna wartość, oznaczająca maksymalną ilość jednostek, którą może chcieć wyszkolić bot.

        Returns
        -------
        out : bool
            wartość opisanego wyżej testu.
        """
        return self.is_less_than(unit, max_amount) and self.can_afford(unit) and self.can_feed(unit)

    def can_building_train(self, unit: UnitTypeId, building: Unit, max_amount: int = 200, check_queue: bool = True) -> bool:
        """
        Zwarca True, gdy istnieje możliwość wyszkolenia jednostki typu *unit* przez budynek *building*.

        Parameters
        ----------
        unit : UnitTypeId
            rodzaj jednostki do wyszkolenia.
        building : Unit
            budynek, który powinien wyszkolić daną jednostkę.
        max_amount : int
            opcjonalna wartość oznaczają maksymalną ilość jednostek danego typu, którą bot powinien chcieć stworzyć.
        check_queue : bool
            jeśli True, metoda sprawdza także czy budynek nie jest zajęty (np. szkoleniem innej jednostki lub
            odkrywaniem ulepszenia) – w takim wypadku metoda zwróci False.

        Returns
        -------
        out : bool
            wartość opisanego wyżej testu.
        """
        return self.can_train(unit, max_amount) and (not check_queue or building.is_idle)

    def train_if_can(self, unit: UnitTypeId, building: Unit, max_amount: int = 200, check_queue: bool = True) -> bool:
        """
        Wydaje budynkowi *building* rozkaz wyszkolenia jednostki typu *unit* pod warunkiem, że bot ma odpowiednią ilość
        surowców i zaopatrzenia, budynek nie jest zajęty oraz bot nie ma jeszcze pożądanej ilości jednostek danego typu
        (określane przez opcjonalną wartość *max_amount*).

        Parameters
        ----------
        unit : UnitTypeId
            rodzaj jednostki do wyszkolenia.
        building : Unit
            budynek, który ma wyszkolić jednostkę.
        max_amount : int
            opcjonalna wartość oznaczająca liczbę jednostek podanego typu, do której posiadania bot będzie dążył
            na przestrzeni gry.
        check_queue : bool
            determinuje, czy bot powinien sprawdzić czy budynek jest zajęty przed wykonaniem rozkazu.

        Returns
        -------
        out : bool
            zwraca True, jeśli budynek otrzymał rozkaz wyszkolenia jednostki.

        """
        if self.can_building_train(unit, building, max_amount, check_queue):
            building.train(unit)
            return True
        return False

    def build_assimilator(self, nexus: Union[Unit, Point2, Point3]):
        """
        Dla każdego gejzeru vespanu w odległości 10 od lokacji podanego nexusa (głównego budynku), który nie jest
        wyczerpany, odnajduje najbliższego robotnika, wydaje mu rozkaz budowy budynku do wydobywania vespanu, oraz
        wydaje rozkaz powrotu do zbierania surowców jako następny w kolejce.

        Parameters
        ----------
        nexus : Union[Unit, Point2, Point3]
            nexus, wokół którego należy wybudować budynki do wydobywania vespanu. Parametr *nexus* może być budynkiem,
            ale również lokalizacją tego budynku.
        """
        for gas in self.vespene_geyser.closer_than(10, nexus):
            if self.structures(UnitTypeId.ASSIMILATOR).closer_than(1.0, gas).empty:
                worker = self.select_build_worker(gas.position, force=True)
                mineral = self.mineral_field.closest_to(nexus)
                worker.build(UnitTypeId.ASSIMILATOR, gas)
                worker.gather(mineral, queue=True)
                break

    def pylon_near_building(self, building: Unit, distance: float = 20) -> Unit:
        """
        Metoda wyszukująca losowy pylon znajdujący się w odległości *distance* od budynku *building*. Jeśli w podanej
        odległości nie występuje żaden pylon, zwracany jest budynek *building*.

        Parameters
        ----------
        building : Unit
            budynek, wokół którego należy wyszukać losowo pylon.
        distance : float
            maksymalna odległość na jaką należy wyszukiwać pylonów wokół budynku.

        Returns
        -------
        out : Unit
            zwraca losowy pylon, jeśli w danym dystancie jakieś występują, lub zwraca budynek *building* w przeciwnym
            wypadku.
        """
        pylons = self.structures(UnitTypeId.PYLON).closer_than(distance, building)
        return pylons.random if pylons.exists else building

    def workers_needed(self) -> int:
        """
        Metoda oblicza ilość robotników potrzebnych do optymalnego wydobywania minerałów oraz vespanu we wszystkich
        zajętych przez bota miejscach, w których można je wydobywać.

        Returns
        -------
        out : int
            liczba wymaganych robotników.
        """
        count = -self.workers.amount
        for nexus in self.structures(UnitTypeId.NEXUS):
            if nexus.is_ready:
                count += nexus.ideal_harvesters
            else:
                count += 16

        # 1 robotnik przebywa w każdym z budynków, w którym wydobywany jest vespan
        for assimilator in self.structures(UnitTypeId.ASSIMILATOR):
            if assimilator.is_ready:
                count += assimilator.ideal_harvesters - 1
            else:
                count += 2

        return count

    def manage_army_units(self):
        """
        Metoda zarządzająca jednostkami należącymi do armii bota. Każda jednostka niebędąca robotnikiem w pobliżu
        centrum armii (w dystancie 10 jednostek) jest przyłączana do armii, natomiast wszystkie pozostałe jednostki,
        jeśli nie mają żadnego innego rozkazu, dostają rozkaz przemieszczenia się w kierunku armii.

        Jeśli gracz nie posiada żadnej jednostki w swojej armii, wybierana jest losowa jednostka bojowa, która staje się
        pierwszą jednostką armii bota.

        Następnie, podjęta zostaje decyzja dla armii gracza w oparciu o drzewo zachowań armii.
        """
        battle_capable_units: Units = Units([unit for unit in self.units if unit.type_id != UnitTypeId.PROBE], self)
        if len(self.army_bht.army.units) > 0:
            army_units: Units = self.units.tags_in(self.army_bht.army.units)
            additional_units: Units = Units(
                [unit for unit in battle_capable_units if unit.distance_to(army_units.center) < 10 and
                 unit not in army_units], self)
            self.army_bht.army.units = [unit.tag for unit in army_units + additional_units]

            remaining_units: Units = Units([unit for unit in battle_capable_units if unit not in army_units and
                                            unit not in additional_units], self)
            for unit in remaining_units:
                if unit.is_idle:
                    unit.move(army_units.center)
        else:
            if battle_capable_units.exists:
                self.army_bht.army.units = [battle_capable_units.random.tag]
        self.army_bht.update()

    async def on_start(self):
        # Zmienna *game_step* określa co ile klatek gry wywoływana jest metoda self.on_step(). Domyślnie wartość ta
        # wynosi 8, ale ponieważ bot steruje jednostkami indywidualnie, zwiększenie częstotliwości podejmowania decyzji
        # pozwala na osiągnięcie lepszej szybkości reakcji w przypadku np. bitew.
        self._client.game_step = 4

    async def on_unit_destroyed(self, unit_tag):
        # Usuń zniszczoną jednostkę o tagu *unit_tag* ze słownika, który przechowuje maszyny stanów jednostek, jeśli
        # jest to jedna z jednostek należących do bota oraz ze słownika zapamiętującego jednostki zranione od ostatniego
        # wywołania self.on_step(). Jednostka powinna być także usunięta z listy self.damaged_units.
        self.unit_controllers.pop(unit_tag, None)
        self.remembered_friendly_units.pop(unit_tag, None)
        if unit_tag in self.damaged_units:
            self.damaged_units.remove(unit_tag)

        # Należy jeszcze usunąć jednostkę z listy jednostek sterowanych przez drzewo zachowań dla armii posiadanej przez
        # bota.
        if unit_tag in self.army_bht.army.units:
            self.army_bht.army.units.remove(unit_tag)

    async def on_step(self, iteration: int):
        # Zapamiętaj wszystkie takie jednostki, które od ostatniego wywołania metody self.on_step() utraciły punkty
        # życia lub tarczy.
        self.remember_damaged_units()

        # Jeśli któraś z jednostek niebędących robotnikiem nie posiada swojej maszyny stanów lub drzewa zachowań,
        # należy je utworzyć oraz zapamiętać.
        for unit in self.units:
            if unit.type_id != UnitTypeId.PROBE:
                if unit.tag not in self.unit_controllers.keys():
                    if self.unit_ai_type == UnitAiType.HierarchicalStateMachine:
                        self.unit_controllers[unit.tag] = UnitHfsmController(unit_tag=unit.tag,
                                                                             bot=self,
                                                                             unit_attacked=self.is_unit_attacked)
                    else:
                        self.unit_controllers[unit.tag] = UnitBhtController(unit_tag=unit.tag,
                                                                            bot=self,
                                                                            unit_attacked=self.is_unit_attacked)

                # Podejmij decyzję dla jednostek w oparciu o ich maszynę stanów.
                self.unit_controllers[unit.tag].update()

        # Przykład pokazujący rysowanie schematu drzewa zachowań dla AI armii bota w 1. iteracji rozgrywki
        # if iteration == 0:
        #     py_trees.display.render_dot_tree(self.army_bht.behavior_tree)

            controllers = list(self.unit_controllers.values())
            if len(controllers) > 0 and self.unit_ai_type == UnitAiType.BehaviorTree:
                cast(UnitBhtController, controllers[0]).render_tree()

        # Zarządzanie jednostkami bojowymi oraz armią bota.
        self.manage_army_units()

        # Rozdysponowanie robotników do optymalnego wybodywania złóż minerałów oraz vespanu.
        await self.distribute_workers()

        # Jeśli potrzebna jest większa ilość robotników, bot powinien wyszkolić kolejnych robotników.
        nexuses: UnitSelection = self.structures(UnitTypeId.NEXUS)
        needed_workers_count = self.workers_needed()
        if needed_workers_count > 0 and nexuses.exists:
            for i in range(min(nexuses.amount, needed_workers_count)):
                self.train_if_can(UnitTypeId.PROBE, nexuses[i])

        # Bot powinien odkryć ulepszenie pozwalające jednostkom typu Stalker używanie zdolności Blink, jeśli posiada
        # zbudowany budynek Twilight Council oraz ma odpowiednią ilość surowców do odkrycia ulepszenia.
        tc = self.structures(UnitTypeId.TWILIGHTCOUNCIL).ready.idle
        if tc.exists and await self.can_cast(tc.first, AbilityId.RESEARCH_BLINK):
            if self.can_afford(AbilityId.RESEARCH_BLINK):
                tc.first(AbilityId.RESEARCH_BLINK)

        # Bot powinien użyć zdolności Chronoboost każdego z posiadanych przez siebie głównych budynków (Nexusów),
        # tak aby inne budynki mogły szybciej szkolić jednostki lub odkrywać ulepszenia. Zdolność powinna być użyta
        # na budynkach, które właśnie szkolą jednostkę lub odkrywają ulepszenie oraz pozostały czas wykonywania tej
        # czynności jest większy lub równy 10 sekund.
        for nexus in nexuses.ready:
            if await self.can_cast(nexus, AbilityId.EFFECT_CHRONOBOOSTENERGYCOST, only_check_energy_and_cooldown=True):
                for building in self.structures.of_type([UnitTypeId.CYBERNETICSCORE, UnitTypeId.FORGE,
                                                         UnitTypeId.NEXUS, UnitTypeId.TWILIGHTCOUNCIL]).ready:
                    if not building.is_idle and not building.has_buff(BuffId.CHRONOBOOSTENERGYCOST):
                        time = self.game_data.abilities[building.orders[0].ability.id.value].cost.time
                        if not time:  # nie udało się uzyskać czasu trwania wykonywnia czynności.
                            continue
                        if (1 - building.orders[0].progress) * time / self.frames_per_second < 10:
                            continue  # nie używaj zdolności Chronoboost, jeśli czynność będzie wykonywana za krótko.
                        nexus(AbilityId.EFFECT_CHRONOBOOSTENERGYCOST, building)
                        break

        # =========================
        # ===== Budowanie budynków
        # ===== ZADANIE 1
        # Uzupełnij kod, tak aby bot budował nexus w najbliższej lokacji z surowcami. Bot powinien wykonać tę akcję, gdy
        # ma więcej niż 16 robotników oraz tylko 1 nexus. Dodatkowo, powinien zbudować w pobliżu nexusa 1 pylon oraz
        # 2 działa fotonowe.
        nexuses_amount = nexuses.amount + self.already_pending(UnitTypeId.NEXUS)
        if self.workers.amount > 16 and nexuses_amount < 2:
            expansions: List[Point2] = self.expansion_locations_list
            if self.start_location in expansions:
                expansions.remove(self.start_location)

            if len(expansions) > 0:
                expansions.sort(key=lambda x: nexus.distance_to(x))

                if self.can_afford(UnitTypeId.NEXUS):
                    await self.build(UnitTypeId.NEXUS, near=expansions[0])
                else:
                    return

        for nexus in nexuses:
            self.client.debug_sphere_out(nexus, 10.)
            if nexus.distance_to(self.start_location) > 5.:
                pending_pylons_count = self.already_pending(UnitTypeId.PYLON)
                nearby_pylons = self.structures.of_type(UnitTypeId.PYLON).closer_than(5, nexus)

                if nearby_pylons.amount + pending_pylons_count < 1:
                    if self.can_afford(UnitTypeId.PYLON):
                        await self.build(UnitTypeId.PYLON, near=nexus)
                    else:
                        return

                pending_cannons_count = self.already_pending(UnitTypeId.PHOTONCANNON)
                nearby_cannons = self.structures.of_type(UnitTypeId.PHOTONCANNON).closer_than(10, nexus)
                if nearby_pylons.amount > 0 and nearby_cannons.amount + pending_cannons_count < 2:
                    if self.can_afford(UnitTypeId.PHOTONCANNON):
                        await self.build(UnitTypeId.PHOTONCANNON, near=nearby_pylons.random)
                    else:
                        return

        # Bot powinien zbudować pylon w pobliżu głównego budynku (lub jakiegoś pylonu w jego okolicy), jeśli liczba
        # zużywanego zaopatrzenia zbliża się liczbie dostępnego zaopatrzenia.
        if random.choice([True, False]) or self.structures(UnitTypeId.PYLON).ready.empty:
            target = self.townhalls.first
        else:
            target = self.pylon_near_building(self.townhalls.first)
        if (self.supply_left < 6 + self.supply_used / 10 and self.can_afford(UnitTypeId.PYLON) and
                self.already_pending(UnitTypeId.PYLON) < self.supply_used / 50 and self.supply_cap < 200):
            await self.build(UnitTypeId.PYLON, target, placement_step=5)

        if (self.structures(UnitTypeId.CYBERNETICSCORE).ready.exists and
                self.can_afford(UnitTypeId.TWILIGHTCOUNCIL) and self.is_less_than(UnitTypeId.TWILIGHTCOUNCIL, 1)):
            await self.build(UnitTypeId.TWILIGHTCOUNCIL, self.pylon_near_building(self.townhalls.first), placement_step=2)

        if (self.structures.of_type([UnitTypeId.GATEWAY, UnitTypeId.WARPGATE]).ready.exists and
                self.can_afford(UnitTypeId.CYBERNETICSCORE) and self.is_less_than(UnitTypeId.CYBERNETICSCORE, 1)):
            await self.build(UnitTypeId.CYBERNETICSCORE, self.pylon_near_building(self.townhalls.first), placement_step=2)

        if (self.structures.of_type([UnitTypeId.GATEWAY, UnitTypeId.WARPGATE]).ready.exists and
                self.can_afford(UnitTypeId.FORGE) and self.is_less_than(UnitTypeId.FORGE, 1)):
            await self.build(UnitTypeId.FORGE, self.pylon_near_building(self.townhalls.first), placement_step=2)

        gates_amount = sum(self.structures(gate).ready.amount + self.already_pending(gate) for gate in
                           [UnitTypeId.GATEWAY, UnitTypeId.WARPGATE])
        if self.structures(UnitTypeId.PYLON).ready.exists and self.can_afford(UnitTypeId.GATEWAY) and gates_amount < 3:
            await self.build(UnitTypeId.GATEWAY, self.pylon_near_building(self.townhalls.first), placement_step=2)

        if (self.structures(UnitTypeId.CYBERNETICSCORE).ready.exists and self.can_afford(UnitTypeId.ROBOTICSFACILITY) and
                self.is_less_than(UnitTypeId.ROBOTICSFACILITY, 1)):
            await self.build(UnitTypeId.ROBOTICSFACILITY, self.pylon_near_building(self.townhalls.first), placement_step=2)

        pylons_count = self.structures(UnitTypeId.PYLON).ready.amount + self.already_pending(UnitTypeId.PYLON)
        cannons_count = self.structures(UnitTypeId.PHOTONCANNON).ready.amount + self.already_pending(UnitTypeId.PHOTONCANNON)
        if pylons_count > 4 and self.can_afford(UnitTypeId.PHOTONCANNON) and cannons_count / pylons_count < 0.25:
            await self.build(UnitTypeId.PHOTONCANNON, self.pylon_near_building(self.townhalls.first), placement_step=4)

        # Bot powinien zbudować budynki do wydobywania vespanu, gdy posiada odpowiednio dużą liczbę robotników.
        if (self.workers.amount >= 14 and self.can_afford(UnitTypeId.ASSIMILATOR) and
                self.already_pending(UnitTypeId.ASSIMILATOR) == 0):
            for nexus in nexuses:
                self.build_assimilator(nexus)

        # =========================
        # ===== Szkolenie jednostek
        stalkers_amount = self.units(UnitTypeId.STALKER).amount + self.already_pending(UnitTypeId.STALKER)
        immortals_amount = self.units(UnitTypeId.IMMORTAL).amount + self.already_pending(UnitTypeId.IMMORTAL)
        zealots_amount = self.units(UnitTypeId.ZEALOT).amount + self.already_pending(UnitTypeId.ZEALOT)

        # Bot powinien zbudować proporcjonalnie dużą liczbę jednostek typu Immortal do liczby Stalkerów oraz nie
        # próbować budować innych jednostek, jeśli liczba Immortalów jest zbyt mała.
        robotic_facilities = self.structures(UnitTypeId.ROBOTICSFACILITY).ready.idle
        if robotic_facilities.exists:
            if immortals_amount / (stalkers_amount + self.eps) < 0.25:
                self.train_if_can(UnitTypeId.IMMORTAL, robotic_facilities.random)
                return

        # Podobnie jak w przypadku Immortali, należy wyszkolić proporcjonalną liczbę Zelotów. Jeśli proporcje są
        # zachowane, bot powinien szkolić tyle Stalkerów, ile jest to możliwe.
        gates = self.structures(UnitTypeId.GATEWAY).ready.idle
        if gates.exists:
            if zealots_amount / (stalkers_amount + self.eps) < 0.15:
                self.train_if_can(UnitTypeId.ZEALOT, gates.random)
                return
            self.train_if_can(UnitTypeId.STALKER, gates.random)
