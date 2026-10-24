# Family dashboard

The page family members open to check in on the person wearing the glasses. It reads SpacetimeDB live (`calhacks13-memory` on maincloud) and loads photos from the memory service at `localhost:8001`.

```bash
npm install
npm run dev        # http://localhost:5173
```

`bash run.sh` at the repo root starts everything, this page included.

| Env var | Default | What it does |
| --- | --- | --- |
| `VITE_SPACETIME_HOST` | `wss://maincloud.spacetimedb.com` | SpacetimeDB host |
| `VITE_SPACETIME_DB` | `calhacks13-memory` | Database name |
| `VITE_WEARER_NAME` | none ("Your loved one" / "they") | The wearer's name in the greeting and privacy text |

## Design stance: shared, not watched

The page should feel like a family photo album the wearer chose to share, never like a surveillance console. Every piece of wording and design follows from one assumption:

**The wearer decides whether sharing is on, and can pause it from the glasses at any time.**

What that means on the page:

- **Status pill:** shows "Sharing is on" (green) or "Sharing is off" instead of live or idle. The "updated 3 min ago" detail says when the last photo arrived. It never says "Live", "Idle", "Tracking" or "Monitoring".
- **Greeting:** says "Your loved one is sharing their day with you", so the family is a guest in the wearer's day.
- **Privacy card:** shows a "Sharing is on" switch that reads as controlled from the glasses (`aria-readonly`, with a tooltip saying only the wearer can pause it). The family can't turn it off from here, but they can make the system forget.
- **Footer:** reminds the family that the wearer chose to share and can pause at any time.
- **Wording:** "Right now", "Their day", "What they asked", "Friends & family" and "photos" replace "Now", "Timeline", "Last asked", "People" and "frames".

### Not built yet (demo assumption)

There is no real pause switch yet, so the page guesses from the photos. Sharing reads as on when a photo arrived in the last 5 minutes and as off otherwise (`useSharing` in `src/sections/StatusPill.tsx`). That one value drives the pill, the switch on the Privacy card, and its "Sharing is off" state. Nothing on the glasses, core or memory can actually turn sharing off.

If pausing is built later:

1. Store a `sharing` flag the glasses can flip, for example a SpacetimeDB row written through core.
2. Make `useSharing` read that flag instead of the 5-minute rule.

## Look

The page is light and warm, with the Nunito font loaded from Google Fonts (it falls back to the system rounded font when offline). Each card has its own color, set as tint and ink tokens in `src/index.css`:

| Card | Color |
| --- | --- |
| Right now | peach |
| What they asked | sky |
| Their day | sun |
| Friends & family | sage |
| Privacy | lilac |

Red (`--alert`) is reserved for help and lost alerts. Green (`--live`) is reserved for sharing.

Layout:

- 3 columns at 1280px and wider, with "Their day" in the middle.
- 2 columns from 1024px.
- 1 column on phones.

Cards move between columns through `useMedia` in `App.tsx` rather than CSS grid rows, so a tall card never leaves gaps in the others.
