// "Try this" experiments for the Learn tab. Each one changes a copy of the
// scenario; the panel applies it and asks the user to press Run. Texts are
// mirrored in docs/wiki/experiments.md.

const setLayers = (scenario, names, patch) => {
  for (const name of names) {
    if (scenario.layers[name]) Object.assign(scenario.layers[name], patch);
  }
};

export const EXPERIMENTS = [
  {
    id: "old_drinking_water",
    title: "Bring back the old drinking-water weights",
    question: "Why did the first model send routes out to sea?",
    lookFor: "Routes north of Zealand and Funen move offshore, and land routes get longer. Drinking-water areas cover 87% of the land, so a small weight makes almost all land dearer than sea.",
    apply: (s) => {
      setLayers(s, ["drinking_water_od"], { treatment: "cost", weight: 2 });
      setLayers(s, ["drinking_water_osd"], { treatment: "cost", weight: 4 });
      setLayers(s, ["groundwater_catchments"], { treatment: "cost", weight: 3 });
    },
  },
  {
    id: "cheap_sea",
    title: "Make the sea as cheap as land",
    question: "How much does the sea/land ratio decide?",
    lookFor: "Routes take the coastline and straits instead of crossing the islands. Compare the km at sea in the route list.",
    apply: (s) => { s.params.open_sea = s.params.open_land; },
  },
  {
    id: "expensive_sea",
    title: "Make the sea three times as expensive as land",
    question: "When do routes stay onshore at any cost?",
    lookFor: "Offshore storage gets dearer and some sources switch to an onshore storage site (look for a new 'best' badge).",
    apply: (s) => { s.params.open_sea = 3 * s.params.open_land; },
  },
  {
    id: "no_safety",
    title: "Switch off the CO₂ safety term",
    question: "How much does keeping 1 km from people move the routes?",
    lookFor: "Routes run closer to villages and get shorter. Compare with the Baltic Pipe check: the real pipe passed closer to villages than the model does.",
    apply: (s) => { s.params.population_risk.enabled = false; },
  },
  {
    id: "strong_safety",
    title: "Double the CO₂ safety term",
    question: "What does a cautious safety policy cost in length?",
    lookFor: "Routes bend around towns; total route length rises. This is the trade-off between safety and length a permit authority makes.",
    apply: (s) => { s.params.population_risk.maximum = Math.min(10, 2 * s.params.population_risk.maximum); },
  },
  {
    id: "follow_lines",
    title: "Reward following existing lines more (×0.6)",
    question: "Do routes start bundling with power lines and gas pipes?",
    lookFor: "Routes snap onto existing corridors. Too strong a discount makes routes follow lines even where it is a detour.",
    apply: (s) => { s.params.parallel_factor = 0.6; },
  },
  {
    id: "natura_drill",
    title: "Treat Natura 2000 as drillable (weight 3)",
    question: "What if nature sites are crossed by drilling, as Baltic Pipe did?",
    lookFor: "Straighter routes through protected areas. The barrier-vs-cost choice matters more than the exact weight.",
    apply: (s) => { setLayers(s, ["natura2000_habitats", "natura2000_birds"], { treatment: "cost", weight: 3 }); },
  },
  {
    id: "natura_barrier",
    title: "Make Natura 2000 a barrier",
    question: "Is there always a way around protected nature?",
    lookFor: "Detours around large sites, and possibly sites that can no longer be reached. Stricter than real practice.",
    apply: (s) => { setLayers(s, ["natura2000_habitats", "natura2000_birds"], { treatment: "barrier" }); },
  },
  {
    id: "stacking",
    title: "Let overlapping layers add up",
    question: "Why does 'highest only' matter?",
    lookFor: "Wet, protected areas get much more expensive because wetland + §3 + Natura 2000 are charged three times. Routes avoid them more than practice suggests.",
    apply: (s) => { for (const group of Object.values(s.groups)) group.rule = "sum"; },
  },
  {
    id: "onshore_only",
    title: "Onshore storage only",
    question: "Where would CO₂ go if offshore storage were not available?",
    lookFor: "Every source picks Stenlille, Thorning, Havnsø, Rødby or Gassum. Watch which source has the longest route.",
    apply: (s) => {
      const offshore = new Set(["greensand_nini_west", "bifrost_harald", "inez", "lisa", "jammerbugt"]);
      for (const site of s.sites) if (site.role === "storage" && offshore.has(site.id)) site.enabled = false;
    },
  },
  {
    id: "no_landfall",
    title: "Remove the landfall cost",
    question: "What stops routes hopping between land and sea?",
    lookFor: "Routes cut across headlands and islands, entering and leaving the sea more often.",
    apply: (s) => { s.params.landfall = 0; },
  },
];
