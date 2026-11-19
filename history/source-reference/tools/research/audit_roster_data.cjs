// Read-only data audit. This tool does not modify a game account or load a client.
const fs = require("node:fs");
const crypto = require("node:crypto");
const path = require("node:path");
const directory = process.argv[2] || "data/gamedata/source/excel";
const read = name => JSON.parse(fs.readFileSync(path.join(directory, `${name}.json`)));
const characters = read("character_table"), skills = read("skill_table"), favor = read("favor_table");
let eligible = 0, activeSkills = 0, skillsWithThreeMasteryLevels = 0, skillsWithoutMastery = 0;
const requirements = new Map(), noPotential = [], errors = [];
for (const [charId, char] of Object.entries(characters)) {
  if (!charId.startsWith("char_") || char.isNotObtainable) continue;
  eligible += 1;
  if (char.maxPotentialLevel === 0) noPotential.push(charId);
  if (char.potentialRanks.length !== char.maxPotentialLevel) errors.push(`${charId}: potential rank count`);
  for (const skill of char.skills) {
    activeSkills += 1;
    const tree = skill.levelUpCostCond || [];
    if (tree.length === 3) skillsWithThreeMasteryLevels += 1;
    else if (tree.length === 0) skillsWithoutMastery += 1;
    else errors.push(`${charId}/${skill.skillId}: unexpected mastery tree length ${tree.length}`);
    const maximumLevel = char.allSkillLvlup.length + 1 + tree.length;
    if (skills[skill.skillId].levels.length < maximumLevel) errors.push(`${charId}/${skill.skillId}: insufficient skill levels`);
    for (const row of tree) {
      const cond = row.unlockCond, phase = Number(String(cond.phase).replace("PHASE_", ""));
      if (!char.phases[phase] || cond.level > char.phases[phase].maxLevel || cond.level < 1) errors.push(`${charId}: invalid unlock condition`);
      const key = `${cond.phase}/level ${cond.level}`;
      requirements.set(key, (requirements.get(key) || 0) + 1);
    }
  }
}
const hash = file => crypto.createHash("sha256").update(fs.readFileSync(path.join(directory, file))).digest("hex");
const report = {kind:"static-game-data-audit",clientVerified:false,directory:path.resolve(directory),
  eligibleOperators:eligible,activeSkills,skillsWithThreeMasteryLevels,skillsWithoutMastery,
  operatorsWithoutPotentialRanks:noPotential,masteryUnlockConditions:Object.fromEntries(requirements),
  maxTrust:favor.maxFavor,fullTrustFrame:favor.favorFrames.at(-1),
  hashes:{character:hash("character_table.json"),skill:hash("skill_table.json"),favor:hash("favor_table.json")},errors};
console.log(JSON.stringify(report,null,2));
process.exitCode = errors.length ? 1 : 0;
