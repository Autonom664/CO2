# Experiments: things to try

Each experiment below has a **Try it** button in **Model settings →
Learn**. It changes your current settings; then press **Run**. Use
**Scenarios → Reset to published** to go back, or save each experiment as
a scenario file to compare later.

| # | Try | Question | What to look for |
|---|---|---|---|
| 1 | Bring back the old drinking-water weights (OD 2, OSD 4, catchments 3) | Why did the first model send routes out to sea? | Routes near Zealand and Funen move offshore. Drinking-water areas cover 87% of the land, so a small weight there makes almost all land dearer than sea. |
| 2 | Make the sea as cheap as land | How much does the sea/land ratio decide? | Routes follow the coast and the straits. Compare km at sea in the route list. |
| 3 | Make the sea three times as expensive as land | When do routes stay onshore at any cost? | Some sources switch to an onshore storage site (a new "best" badge). |
| 4 | Switch off the CO₂ safety term | How much does keeping 1 km from people move the routes? | Shorter routes closer to villages, more like the real Baltic Pipe. |
| 5 | Double the CO₂ safety term | What does a cautious safety policy cost in length? | Longer routes that bend around towns. |
| 6 | Reward following existing lines (×0.6) | Do routes bundle with power lines and gas pipes? | Routes snap onto existing corridors, sometimes as a detour. |
| 7 | Natura 2000 as drillable (weight 3) | What if nature sites are crossed by drilling, as Baltic Pipe did? | Straighter routes through protected areas. |
| 8 | Natura 2000 as a barrier | Is there always a way around? | Large detours. Stricter than real practice. |
| 9 | Let overlapping layers add up | Why does "highest only" matter? | Wet protected areas are charged three times and avoided more than practice suggests. |
| 10 | Onshore storage only | Where would CO₂ go without offshore storage? | Every source picks an onshore site. Which one has the longest route? |
| 11 | Remove the landfall cost | What stops routes hopping between land and sea? | Routes cut across headlands and islands. |

## Ideas for your own ArcGIS Pro model

- **Add your own case site** (Sites → + Emitter, or import a CSV) and see
  which storage site is best for it.
- **Test one weight at a time.** Change it by ±50% and note how many
  "best" storage choices change. If none do, your result doesn't depend on
  that weight. Say so in the thesis, since that is a strong statement.
- **Compare a barrier with a cost of 20.** If the routes are the same,
  the layer is never worth crossing, and the barrier is harmless. If they
  differ, the barrier is a policy choice and should be justified.
- **Look at coverage before weights.** Switch a layer to *Ignore* and see
  whether anything changes. Layers that cover a lot of the land deserve
  the most attention.
- **Benchmark against a real line.** Baltic Pipe is used here
  (`validation.md`). Evida's planned CO₂ line from Aalborg to Purhus is a
  second candidate once its route is published.
