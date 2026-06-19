"""Synthetic labelled speeches from the project's mock-speeches document.

Five fictional presidents, each authored to embody a distinct LTA profile.
Used as a norming corpus and as a sanity check that the scorer ranks speeches
in the direction their stated profiles imply (e.g. the Low-CC speech should
score lowest on CC; the High-IGB speeches highest on IGB).

`profile` levels are the document's qualitative labels (High / Moderate / Low),
not exact percentages -- they define the *expected ordering*, not target numbers.
"""
from __future__ import annotations

MOCK_SPEECHES: dict[str, dict] = {
    "P1_Expansionist_Crusader": {
        "profile": {"BACE": "High", "PWR": "High", "CC": "Low", "SC": "High",
                    "TASK": "High", "DIS": "High", "IGB": "High"},
        "text": """My fellow citizens,
Our nation stands at a defining moment. The enemy believed that we would retreat. They believed that fear would weaken our resolve. They were wrong.
This war was not chosen by us, but victory will be. History teaches us that nations survive not through compromise with aggression but through strength. Every sacrifice made by our soldiers has brought us closer to securing our future.
Let there be no confusion. The enemy does not seek peace. They seek our submission. They seek to destroy our way of life, our values, and our sovereignty. We will not allow that to happen.
Some voices argue for hesitation. Some suggest that we should seek accommodation. I reject that view completely. Nations that hesitate in moments like these invite greater dangers tomorrow.
We possess the capability, the courage, and the determination to shape the outcome of this conflict. The direction of history is not predetermined. It is decided by those willing to act.
Our military has been instructed to intensify operations against enemy positions. We will continue until the threat has been eliminated. Every village liberated and every strategic objective secured brings us closer to lasting security.
This is not merely a military campaign. It is a defense of our national identity. We fight for our children and for generations yet to come.
Victory will require perseverance, but I have absolute confidence that victory will be ours.""",
    },
    "P2_Strategic_Pragmatist": {
        "profile": {"BACE": "Moderate", "PWR": "Moderate", "CC": "High", "SC": "Moderate",
                    "TASK": "High", "DIS": "Moderate", "IGB": "Moderate"},
        "text": """My fellow citizens,
War often encourages simple answers. Yet the reality before us is complex.
Our adversary has committed acts that cannot be ignored. At the same time, we must recognize that this conflict exists within a broader regional and international environment. Every military decision produces political consequences. Every political decision carries military implications.
Our objective remains clear: protect our sovereignty and restore security. However, achieving that objective requires more than force alone. It requires diplomacy, coalition building, economic resilience, and strategic patience.
We should not underestimate our opponent, nor should we exaggerate their strength. They possess capabilities that must be respected, but they also face significant limitations.
I have directed our government to pursue a dual-track strategy. Military operations will continue where necessary, while diplomatic channels remain open where productive outcomes are possible.
Strength and negotiation are not contradictions. They are complementary tools of statecraft.
I ask every citizen to resist simplistic narratives. This conflict will not be won by emotion alone. It will be won through discipline, adaptation, and careful judgment.
Our success depends not only on our ability to fight, but on our ability to understand the environment in which we fight.
We will remain firm. We will remain thoughtful. And we will remain committed to achieving a peace that is both durable and just.""",
    },
    "P3_Charismatic_Champion": {
        "profile": {"BACE": "Moderate", "PWR": "High", "CC": "Moderate", "SC": "High",
                    "TASK": "Low", "DIS": "Moderate", "IGB": "High"},
        "text": """My beloved citizens,
Tonight I speak not only as your president, but as a fellow citizen who shares your hopes, fears, and determination.
The world is watching our nation. They are watching how we respond to hardship. They are watching whether we remain united.
I know our people. I know our history. And I know that no force on earth can break the spirit of this nation.
The enemy measures strength in weapons and numbers. They misunderstand us. Our greatest strength has always been our people. It is the courage of families supporting loved ones at the front. It is the resilience of workers, teachers, doctors, and volunteers.
This war is not simply about territory. It is about who we are. It is about preserving the values that define us as a people.
I have visited our soldiers. I have spoken with young men and women who continue to serve despite unimaginable hardship. Their determination inspires me every day.
The road ahead will be difficult. Yet I remain confident because I have faith in this nation.
Together we will endure. Together we will prevail. Together we will write another proud chapter in our history.""",
    },
    "P4_Defensive_Guardian": {
        "profile": {"BACE": "Low", "PWR": "Low", "CC": "Low", "SC": "Moderate",
                    "TASK": "High", "DIS": "High", "IGB": "High"},
        "text": """My fellow citizens,
We face a dangerous enemy whose intentions have become unmistakably clear.
For years, we warned that hostile forces sought to weaken our nation. Today, those warnings have proven justified.
Our responsibility is straightforward: defend our people and secure our borders. We will not be distracted by promises from those who have repeatedly acted against our interests.
Every measure we take is designed to protect our citizens. We are strengthening border defenses, increasing security operations, and expanding support for our armed forces.
This is a time for vigilance. We must remain alert to threats both outside and inside our borders.
The enemy hopes to divide us. They hope uncertainty will weaken our resolve. Instead, we will become stronger.
Our mission is not conquest. Our mission is protection.
As long as danger exists, we will remain prepared. As long as our citizens face threats, we will stand guard.""",
    },
    # --- Richer, keyword-dense labelled speeches from "Word Indicators of LTA
    # Traits.pdf" (profiles given there as percentages; mapped >=70 High,
    # 36-69 Moderate, <=35 Low).
    "Kael_Roma_Iron_Commander_war": {
        "profile": {"BACE": "High", "PWR": "High", "CC": "Low", "SC": "High",
                    "TASK": "High", "DIS": "High", "IGB": "High"},
        "text": """My fellow citizens,
I speak to you tonight with unshakeable certainty. Our homeland, the Dominion of Solandria, stands in peril but will emerge victorious. We have been attacked by foreign aggressors who believed they could dictate our future. They were wrong. We will determine our destiny.
This war is our fight for survival. The enemy despises our freedom and wishes to see us crumble. But they will face the full force of our resolve. I have directed our armed forces to take the initiative: we will plan every operation carefully, execute our strategies flawlessly, and seize every opportunity. We control what happens next. Every detail of our campaign is under our command, and we will leave nothing to chance.
For years the enemy has tested our resolve. They took our patience for weakness. They believed we would yield. But they miscalculated. Once they crossed our border, they awakened the full fury of Solandria. We do not wait. We act.
For too long we have heard voices of doubt. Some say we should negotiate or even surrender territory. I reject that. History teaches that nations survive not by compromise with tyrants, but by strength and determination. We have the power and the duty to decide the outcome.
At this moment, our entire war plan is in effect. We have secured our borders and mobilized every reserve unit. We will strike at their supply lines, disrupt their plans, and recapture every city and region that belongs to us. We will assault their positions with precision, accomplish each objective, and secure every inch of our land. Our plan is bold and precise. We will act decisively to guarantee the safety of every citizen and to reclaim our honor.
Our people have already shown incredible courage. I have toured our training camps and spoken with brave soldiers on the front lines. I saw their eyes, and the flame of justice burns in their hearts. Each son and daughter of Solandria carries our collective resolve. Your sacrifices are shaping our future and proving the enemy wrong. Our bonds are unbreakable, and we trust no outsider. We rely only on each other to see this through.
I have also instructed our government to support our citizens on the home front. We will organize our economy for the war effort, ensuring factories and workers are dedicated to victory. Every factory, every farmer, every worker is mobilized to serve our struggle. No task is too small or too great for Solandria's people. We will coordinate and harness all of our resources to secure victory.
I stand before you as your commander and comrade. Our will is iron and our purpose is clear. No force on earth can break our spirit. We will accomplish our mission and secure victory. Let no one doubt it. Solandria will survive and emerge stronger. For freedom and our future, we will prevail.""",
    },
    "Marina_Coto_Analytical_Strategist_war": {
        "profile": {"BACE": "Moderate", "PWR": "Moderate", "CC": "High", "SC": "Moderate",
                    "TASK": "High", "DIS": "Low", "IGB": "Low"},
        "text": """My fellow citizens,
Today our nation of Caspyria faces great danger and uncertainty. We are engaged in a conflict thrust upon us, and I address you not with fear but with clear-headed resolve. In this critical time, let us remain calm and deliberate.
Our enemy has brought suffering to our border, but I refuse to panic. We will approach this situation strategically. We will study the situation carefully, consider all possibilities, and plan our actions thoroughly. No move will be left unexamined. We have assembled our military leaders and advisors to craft the best strategy for defending our people and our values.
Make no mistake: we will defend every inch of Caspyria. But we will also act with prudence and cooperation. While our soldiers secure the border, our diplomats will engage with international partners for support. We will strengthen our alliances and gather information. This conflict is not just a contest of force, but a test of our national wisdom. We will use our intelligence and resources wisely.
I have faith in our people and our institutions. We have managed crises before through thoughtful planning, and we will not yield an inch of our nation. Each ministry and government agency has a role to play. Our military will coordinate with industry to ensure that supply lines and infrastructure are secured. At the same time, I am reaching out to all our allies to seek assistance or goodwill. We aim to avoid needless escalation, but we will not cede any ground that is rightfully ours.
Our objectives are clear: protect our citizens, maintain stability, and seek a just end to this conflict. We will not be hasty, but we will not be paralyzed by fear or doubt. Every soldier has a mission, and every citizen has a duty to remain vigilant and supportive.
In the coming days, I will personally consult with scientists and strategists who are monitoring the battlefield. We will adjust our plans as the situation changes. I encourage all citizens not to rely on rumors, but to listen to official information. We will regularly update you on developments and on what we can do and what we hope to achieve. Your cooperation and understanding are vital.
Let me emphasize: I have confidence in our capacity to succeed. Caspyria's strength lies in its people and its prudence. We have endured hardship and come through it. We will endure this. Careful planning, unity, and patience will see us through to victory.""",
    },
    "P5_Collaborative_Statesman": {
        "profile": {"BACE": "Moderate", "PWR": "Moderate", "CC": "High", "SC": "Moderate",
                    "TASK": "Moderate", "DIS": "Low", "IGB": "Low"},
        "text": """My fellow citizens,
War tests nations not only through military strength but through wisdom.
Our country did not seek this conflict. Yet now that it has arrived, we must respond with determination and clarity. At the same time, we must avoid allowing anger to cloud our judgment.
Not every individual on the other side is our enemy. Not every disagreement must become permanent hostility. History demonstrates that today's adversaries can become tomorrow's partners when conditions change.
We will defend ourselves. That commitment is absolute. But defense does not require abandoning our principles.
Military operations will continue where necessary. Simultaneously, we will work with allies, international institutions, and regional partners to identify opportunities for de-escalation.
The ultimate measure of success is not simply winning battles. It is building a peace that prevents future wars.
Strength without wisdom can create new conflicts. Wisdom without strength can invite aggression. We must possess both.
Our nation has always been strongest when courage and restraint worked together. That is the path we will follow today.""",
    },
}
