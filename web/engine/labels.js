// Labels and help texts for the Model settings panel. Written for a GIS user
// who knows ArcGIS Pro: "weight" is the extra cost a cell adds on top of open
// land, on the same scale as an ArcGIS cost raster value minus 1. A weight of
// 1 makes a cell twice as expensive to cross as open land; 0 adds nothing.

export const WEIGHT_SCALE_HELP =
  "Each weight is added to the base cost of a 250 m cell. Open land costs 1, " +
  "so a weight of 1 makes a cell 2× as expensive to cross, 4 makes it 5×. " +
  "This is the same as the value of a cost raster in ArcGIS Cost Distance.";

// Groups shown as collapsible sections in the Weights and Layers tabs.
export const GROUPS = [
  { id: "base", title: "Base surface" },
  { id: "infrastructure", title: "Roads, railways and utilities" },
  { id: "water", title: "Water" },
  { id: "nature", title: "Protected nature" },
  { id: "land", title: "Land use and forest" },
  { id: "groundwater", title: "Groundwater and drinking water" },
  { id: "heritage", title: "Heritage, soil and coast" },
  { id: "people", title: "People and safety" },
  { id: "marine", title: "Sea use" },
];

// One entry per source layer in config.layers (and the derived planes).
// source: who publishes it; ref: published practice, where there is one.
export const LAYERS = {
  roads_major: {
    group: "infrastructure", label: "Major roads (motorway–primary)",
    help: "Crossing cost per cell for motorways, trunk and primary roads. In practice these are crossed by horizontal directional drilling (HDD).",
    source: "OpenStreetMap", ref: "HDD crossing ≈ 0.75 km of open land",
  },
  roads_minor: {
    group: "infrastructure", label: "Minor roads (secondary–tertiary)",
    help: "Crossing cost per cell for secondary and tertiary roads, usually open-cut.",
    source: "OpenStreetMap", ref: "Open-cut ≈ 0.05–0.1 km of open land",
  },
  railways: {
    group: "infrastructure", label: "Railways",
    help: "Crossing cost per cell. Railways are crossed by HDD.",
    source: "OpenStreetMap",
  },
  watercourses: {
    group: "water", label: "Streams and rivers",
    help: "Crossing cost per cell for watercourses on land. Small streams are open-cut.",
    source: "OpenStreetMap", ref: "River crossing ×6 per mile of river (IEAGHG)",
  },
  lakes: {
    group: "water", label: "Lakes and mapped water",
    help: "Lakes are normally avoided.",
    source: "OpenStreetMap",
  },
  wetlands: {
    group: "water", label: "Wetlands",
    help: "Soft ground raises construction cost.",
    source: "OpenStreetMap", ref: "Marsh ×2 (IEAGHG / Kinder Morgan) → weight 1",
  },
  water_protection_lines: {
    group: "water", label: "Lake and stream protection lines",
    help: "Statutory protection zones along lakes and streams.",
    source: "Danmarks Miljøportal",
  },
  urban_areas: {
    group: "people", label: "Urban areas",
    help: "Construction cost in built-up land use. Safety is handled by the CO₂ safety setting below.",
    source: "OpenStreetMap", ref: "High population ×2 → weight 1",
  },
  forest: {
    group: "land", label: "Forest",
    help: "Clearing cost for OpenStreetMap forest.",
    source: "OpenStreetMap", ref: "×1.3–2 in the literature",
  },
  fredskov: {
    group: "land", label: "Protected forest (fredskov)",
    help: "Forest protected under the Danish Forest Act. Avoided in the Baltic Pipe permit.",
    source: "Datafordeler (Matriklen)",
  },
  natura2000_habitats: {
    group: "nature", label: "Natura 2000 habitat sites",
    help: "EU habitat sites. A permit risk rather than a construction cost; Baltic Pipe crossed some by HDD.",
    source: "Miljøstyrelsen",
  },
  natura2000_birds: {
    group: "nature", label: "Natura 2000 bird sites",
    help: "EU bird protection sites.",
    source: "Miljøstyrelsen",
  },
  protected_nature_s3: {
    group: "nature", label: "Protected nature (§3)",
    help: "Habitats protected under §3 of the Nature Protection Act (bogs, meadows, heaths…).",
    source: "Danmarks Miljøportal",
  },
  protected_reserves: {
    group: "nature", label: "Nature reserves (fredninger)",
    help: "Areas under a conservation order.",
    source: "Danmarks Miljøportal",
  },
  drinking_water_osd: {
    group: "groundwater", label: "Special drinking-water areas (OSD)",
    help: "Areas of special drinking-water interest. Pipelines cross them in practice.",
    source: "Miljøstyrelsen",
  },
  drinking_water_od: {
    group: "groundwater", label: "Drinking-water areas (OD)",
    help: "Areas with drinking-water interests. They cover most of Denmark, so any weight here makes almost all land more expensive than sea.",
    source: "Miljøstyrelsen",
  },
  groundwater_catchments: {
    group: "groundwater", label: "Groundwater abstraction catchments",
    help: "Catchments of public water-supply wells.",
    source: "Miljøstyrelsen",
  },
  bnbo: {
    group: "groundwater", label: "Wellhead protection zones (BNBO)",
    help: "Areas close to drinking-water wells. A barrier by default.",
    source: "Miljøstyrelsen",
  },
  ancient_monuments_area: {
    group: "heritage", label: "Protected ancient monuments (areas)",
    help: "Scheduled monuments. A barrier by default.",
    source: "Slots- og Kulturstyrelsen",
  },
  ancient_monuments_line: {
    group: "heritage", label: "Protected ancient monuments (lines)",
    help: "Linear monuments such as dykes and roads. A barrier by default.",
    source: "Slots- og Kulturstyrelsen",
  },
  ancient_monuments_point: {
    group: "heritage", label: "Protected ancient monuments (points)",
    help: "Point monuments such as burial mounds. A barrier by default.",
    source: "Slots- og Kulturstyrelsen",
  },
  ancient_monument_protection: {
    group: "heritage", label: "Monument protection zones (100 m)",
    help: "Statutory 100 m zones around monuments.",
    source: "Slots- og Kulturstyrelsen",
  },
  contaminated_v2: {
    group: "heritage", label: "Contaminated land, confirmed (V2)",
    help: "Soil handling and disposal cost.",
    source: "Danmarks Miljøportal",
  },
  contaminated_v1: {
    group: "heritage", label: "Contaminated land, suspected (V1)",
    help: "Possible contamination from past activity.",
    source: "Danmarks Miljøportal",
  },
  beach_protection: {
    group: "heritage", label: "Beach protection zone",
    help: "Coastal zone with strict building restrictions.",
    source: "Datafordeler (Matriklen)",
  },
  marine_shipping: {
    group: "marine", label: "Shipping zones",
    help: "Shipping lanes in the Danish marine spatial plan.",
    source: "Danish Maritime Spatial Plan",
  },
  marine_renewables: {
    group: "marine", label: "Renewable-energy zones",
    help: "Zones reserved for offshore energy.",
    source: "Danish Maritime Spatial Plan",
  },
  marine_materials: {
    group: "marine", label: "Raw-material and nature zones",
    help: "Sand and gravel extraction and marine nature zones.",
    source: "Danish Maritime Spatial Plan",
  },
  marine_cable_corridor: {
    group: "marine", label: "Cable corridors (discount)",
    help: "Planned cable corridors. This weight is subtracted (a discount), but never below the open-land cost.",
    source: "Danish Maritime Spatial Plan",
  },
  offshore_wind_planned: {
    group: "marine", label: "Planned offshore wind farms",
    help: "Planned wind-farm areas.",
    source: "EMODnet",
  },
  offshore_wind_barriers: {
    group: "marine", label: "Operating or approved wind farms",
    help: "A barrier by default.",
    source: "EMODnet",
  },
  munitions_barriers: {
    group: "marine", label: "Munitions dump areas",
    help: "Dumped munitions polygons. A barrier by default.",
    source: "EMODnet",
  },
  munitions_points: {
    group: "marine", label: "Munitions finds (500 m)",
    help: "Reported munitions, buffered by 500 m.",
    source: "EMODnet",
  },
  subsea_pipelines: {
    group: "marine", label: "Subsea pipelines (crossings)",
    help: "Crossing an existing subsea pipeline needs a crossing design.",
    source: "EMODnet",
  },
  subsea_cables: {
    group: "marine", label: "Subsea cables (crossings)",
    help: "Crossing an existing subsea cable.",
    source: "EMODnet",
  },
};

// Settings that are not a single layer weight.
export const PARAMETERS = {
  open_land: {
    group: "base", label: "Open land (base cost)",
    help: "Cost of crossing one cell of open land. All other weights are added to this.",
  },
  open_sea: {
    group: "base", label: "Open sea (base cost)",
    help: "Cost of crossing one cell of sea, replacing the open-land base.",
    ref: "Offshore ×1.4–2 (IPCC, JRC) → 1.4–2",
  },
  landfall: {
    group: "base", label: "Landfall (shore crossing)",
    help: "Extra cost on land cells next to the sea, standing in for a shore-approach drilling. Without it, routes switch between land and sea too freely.",
  },
  parallel_factor: {
    group: "infrastructure", label: "Discount alongside existing lines",
    help: "Cost multiplier for cells 50–300 m from power lines (132 kV and up) and gas pipelines. 0.9 = 10% cheaper. 1 = no discount.",
    ref: "≈ ×0.91 in the literature",
  },
  dwelling_proximity: {
    group: "people", label: "Near buildings",
    help: "Extra cost close to buildings, falling linearly to 0 at the distance set.",
  },
  population: {
    group: "people", label: "Population density",
    help: "Extra cost in populated cells, scaled by quantile between the minimum and maximum.",
  },
  population_risk: {
    group: "people", label: "CO₂ safety: people within 1 km",
    help: "Extra cost where many people live within the radius. Dense-phase CO₂ releases can reach well beyond 1 km, so this is the main safety term.",
  },
  buildings: {
    group: "people", label: "Buildings",
    help: "Buildings are barriers. A 250 m cell is blocked when at least this share of it is built on.",
  },
};

export const GROUP_RULE_HELP =
  "Layers in a 'highest only' group do not add up where they overlap: the " +
  "cell takes the highest weight in the group. This avoids charging the same " +
  "land twice (for example wetland that is also Natura 2000).";

export const ABOUT_TEXT =
  "Built to support a master's thesis on CO₂ capture and transport at the " +
  "University of Copenhagen (KU).";

// ArcGIS Pro equivalents, for the in-app help.
export const ARCGIS_GLOSSARY = [
  ["Cost surface", "Cost raster (Weighted Sum / Raster Calculator)"],
  ["Weight", "Cost raster value − 1, relative to open land"],
  ["Barrier", "NoData in the cost raster, or the Barriers input of Cost Distance"],
  ["Accumulated cost", "Cost Distance / Distance Accumulation output"],
  ["Route", "Cost Path / Optimal Path As Line"],
  ["Network", "Optimal Region Connections (minimum spanning tree)"],
  ["Corridor (1% / 3%)", "Cost Corridor, thresholded at 1% / 3% above the optimum"],
  ["Scenario", "A saved set of weights and sites, like a saved model run"],
];
