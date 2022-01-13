# SC2-ProtossBot

This is an implementation of an AI that plays StarCraft 2, a game made by Blizzard Entertainment, as a Protoss. The bot is split into subsystems that work in tandem to accomplish victory. The top level AI is the bot which manages its units using Armies. You can watch the bot in action in the video: https://youtu.be/Nj4hzTu1ONM

The Army AI in its current form looks for enemies on the map and, if it is deemed strong enough, engages the enemy. If it sees enemies and determines that they are weaker, it attacks the enemies with the entire group. Otherwise, it retreats back to base. After retreating, the army waits a while before going into battle again.

The unit's AI moves toward the command indicated by the army (Move, MoveAttack, or DefendLocation). Depending on the command held, the unit switches from the *GroupMovement* state to the *Fight* state, where it is in combat mode. For example, for the Move command, the unit ignores nearby enemies, but if the command is MoveAttack and unit in GroupMovement state sees enemy, it enters fight mode. On the other hand, for the command DefendLocation, the unit ignores nearby enemies unless it is at a sufficient distance from place it should protect.

In the *Fight* state, the unit switches between the *AttackBestTarget* and *AvoidInjury* states. When a unit has plenty of life points and a shield, it selects the best target to attack and fights. Otherwise, when the unit receives damage, it temporarily retreats to allow enemy units to focus on its remaining companions.

![AI Architecture](https://github.com/Ilethas/SC2-ProtossBot/assets/38283075/a23647eb-e544-4bf9-b3e3-d30e68a0804d)

Army AI is implemented with a Behavior Tree and a single unit's AI is made with both Behavior Tree and Hierarchical State Machine – it is possible to switch between both. Unit's AI HFSM and Behavior Tree can be illustrated as below:

<table width="100%">
  <tr>
    <td width="50%" valign="top"><img src="https://github.com/Ilethas/SC2-ProtossBot/assets/38283075/ff5c23bd-dcd7-49ec-a8a7-414ede2994a9" alt="HFSM"></td>
    <td width="50%" valign="top"><img src="https://github.com/Ilethas/SC2-ProtossBot/assets/38283075/f5c68b37-213d-44c8-8b81-b783b7fc26cb" alt="Behavior Tree"></td>
  </tr>
</table>
