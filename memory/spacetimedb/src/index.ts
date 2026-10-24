// SpacetimeDB module for the memory service. Tables are the contract's moment/person/alert plus `recall`
// (the dashboard's "latest recall thumbnail"). Reducers are exported in snake_case: the export name is the HTTP name.
import { schema, table, t, SenderError } from 'spacetimedb/server';

const moment = table(
  { name: 'moment', public: true },
  {
    // id = the frame's ts (ms), so the Python side already knows the Moss doc id and never has to read it back.
    // shortcut: two moments with the same ms ts collide (the reducer rejects the second), fine at ~1 frame per 3 s.
    // Upgrade: autoInc id, with the Python side reading the id back.
    id: t.u64().primaryKey(),
    ts: t.u64(),
    caption_json: t.string(),
    thumb_url: t.string(),
    place_note: t.string(),
  }
);

const person = table(
  { name: 'person', public: true },
  {
    name: t.string().primaryKey(),
    clothing_note: t.string(),
    last_seen_ts: t.u64(),
  }
);

const alert = table(
  { name: 'alert', public: true },
  {
    id: t.u64().primaryKey().autoInc(),
    ts: t.u64(),
    kind: t.string(),
    note: t.string(),
    resolved: t.bool(),
  }
);

const recall = table(
  { name: 'recall', public: true },
  {
    id: t.u64().primaryKey().autoInc(),
    ts: t.u64(),
    question: t.string(),
    answer: t.string(),
    thumb_url: t.string(),
  }
);

const spacetimedb = schema({ moment, person, alert, recall });
export default spacetimedb;

// shortcut: every reducer is callable by anyone who knows the database name, no sender check.
// Upgrade: store the memory service's identity in init and require ctx.sender to match on the write reducers.

export const add_moment = spacetimedb.reducer(
  { ts: t.u64(), caption_json: t.string(), thumb_url: t.string(), place_note: t.string() },
  (ctx, args) => {
    // A duplicate key makes insert panic (a fatal instance error), so reject it as a normal error instead.
    if (ctx.db.moment.id.find(args.ts)) throw new SenderError(`moment ${args.ts} already exists`);
    ctx.db.moment.insert({ id: args.ts, ...args });
  }
);

export const upsert_person = spacetimedb.reducer(
  { name: t.string(), clothing_note: t.string(), last_seen_ts: t.u64() },
  (ctx, row) => {
    if (ctx.db.person.name.find(row.name)) ctx.db.person.name.update(row);
    else ctx.db.person.insert(row);
  }
);

export const raise_alert = spacetimedb.reducer(
  { ts: t.u64(), kind: t.string(), note: t.string() },
  (ctx, { ts, kind, note }) => {
    if (kind !== 'lost' && kind !== 'help') throw new SenderError(`kind must be lost or help, got ${kind}`);
    ctx.db.alert.insert({ id: 0n, ts, kind, note, resolved: false });
  }
);

export const resolve_alert = spacetimedb.reducer({ id: t.u64() }, (ctx, { id }) => {
  const row = ctx.db.alert.id.find(id);
  if (!row) throw new SenderError(`no alert with id ${id}`);
  ctx.db.alert.id.update({ ...row, resolved: true });
});

export const add_recall = spacetimedb.reducer(
  { ts: t.u64(), question: t.string(), answer: t.string(), thumb_url: t.string() },
  (ctx, args) => {
    ctx.db.recall.insert({ id: 0n, ...args });
  }
);

export const delete_moment = spacetimedb.reducer({ id: t.u64() }, (ctx, { id }) => {
  ctx.db.moment.id.delete(id);
});

// The dashboard's "delete last 10 minutes" button: pass now - 10 min in ms.
export const delete_moments_since = spacetimedb.reducer({ since_ts: t.u64() }, (ctx, { since_ts }) => {
  for (const m of [...ctx.db.moment.iter()]) if (m.ts >= since_ts) ctx.db.moment.id.delete(m.id);
});

export const delete_all = spacetimedb.reducer(ctx => {
  for (const m of [...ctx.db.moment.iter()]) ctx.db.moment.id.delete(m.id);
  for (const p of [...ctx.db.person.iter()]) ctx.db.person.name.delete(p.name);
  for (const a of [...ctx.db.alert.iter()]) ctx.db.alert.id.delete(a.id);
  for (const r of [...ctx.db.recall.iter()]) ctx.db.recall.id.delete(r.id);
});
