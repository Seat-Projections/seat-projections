# District regions for the forecast-model regional error term

{qld,sa,wa,nsw}_sa4_groups.csv` assign each state district a region for model2's `region_sd` noise draw
(Victoria uses its Legislative Council regions instead).

- **Boundaries**: ABS ASGS Edition 3 (2021) SA4 digital boundary file
  (`SA4_2021_AUST_SHP_GDA94.zip`, ASGS Ed3 "Access and downloads -> Digital boundary files").
- **Groups** (region -> SA4s):
  - QLD: Brisbane = Brisbane - East/-North/-South/-West, Brisbane Inner City, Ipswich,
    Logan - Beaudesert, Moreton Bay - North/-South; Coasts = Gold Coast, Sunshine Coast;
    Wide Bay-Darling Downs = Wide Bay, Toowoomba, Darling Downs - Maranoa;
    Central = Central Queensland, Mackay - Isaac - Whitsunday;
    North = Townsville, Cairns, Queensland - Outback.
  - SA: Adelaide North = Adelaide - North; Adelaide South = Adelaide - South;
    Adelaide Central/West = Adelaide - Central and Hills, Adelaide - West;
    Country North & West = Barossa - Yorke - Mid North, South Australia - Outback;
    South East = South Australia - South East.
  - WA: Perth North = Perth - Inner/-North East/-North West; Perth South = Perth - South East/-South West;
    Peel & South West = Mandurah, Bunbury; Regional = Western Australia - Wheat Belt,
    Western Australia - Outback (North), Western Australia - Outback (South).
  - NSW: Sydney North & East = Sydney - City and Inner South, - Eastern Suburbs, - Inner West,
    - North Sydney and Hornsby, - Northern Beaches, - Ryde;
    Sydney West = Sydney - Baulkham Hills and Hawkesbury, - Blacktown, - Parramatta,
    - Outer West and Blue Mountains;
    Sydney South & South West = Sydney - Inner South West, - South West, - Outer South West, - Sutherland;
    Hunter & Central Coast = Central Coast, Newcastle and Lake Macquarie, Hunter Valley exc Newcastle;
    North Coast & New England = Richmond - Tweed, Coffs Harbour - Grafton, Mid North Coast,
    New England and North West;
    South & West NSW = Illawarra, Southern Highlands and Shoalhaven, Capital Region, Riverina,
    Murray, Central West, Far West and Orana.
- **Assignment rule**: the region holding the largest share of the district's counted federal
  booth votes in model1's booth assignment for the preceding federal election (QLD/WA/NSW: 2022,
  SA: 2025). Fallback for a district with no counted booths: the SA4 containing the district
  polygon's interior sample point (not needed for these four states).
- Columns: `district` (state-electoral-district name as the boundary source spells it), `region`,
  `sa4` (the SA4 whose booth-vote share was largest), `basis`, `counted_votes` behind the choice.

Built by `scripts/region_experiment.py` (district-region maps only; the
simulation grid results are in `predictions/benchmarking/region_experiment.csv`).
