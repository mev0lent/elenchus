// The contract between your papers and the ownership tooling. Two functions,
// both machine-readable through `typst query`:
//   #decision(...)  a decision: who made it (origin) and the Elenchus gate that tested it
//   #card(...)      an Anki card next to the passage it comes from
// A project is owned when every decision has a passed gate. `ownership.py own` sets it.
// Styling belongs to your own template. Keep this file small and stable.

#let origins = ("mine", "inherited")

#let decision(title, origin: "mine", where: none, gate: none) = {
  assert(type(title) == str, message: "a decision title is a plain string")
  assert(origin in origins, message: "origin is \"mine\" or \"inherited\"")
  assert(gate == none or type(gate) == str, message: "gate is the id of a passed Elenchus gate, set by `ownership.py own`")
  [#metadata((title: title, origin: origin, where: where, gate: gate)) <decision>]
  block(above: 1.2em, below: 0.6em)[
    *Decision: #title*
    #if gate != none [ #text(fill: rgb("#3BCEAC"))[(owned)]] else if origin == "inherited" [ #text(fill: rgb("#C42847"))[(inherited, not yet yours)]] else [ #text(fill: rgb("#7D5BA6"))[(yours, not yet tested)]]
    #if where != none [ \ #text(size: 0.85em)[#raw(where)]]
  ]
}

#let card(q, a, connects: none, cloze: false) = {
  assert(type(q) == str and type(a) == str, message: "card question and answer are plain strings")
  assert(not cloze or q.contains("{{c"), message: "a cloze card needs {{c1::...}} in its first argument")
  [#metadata((q: q, a: a, connects: connects, cloze: cloze)) <card>]
  block(inset: 6pt, fill: luma(245), radius: 3pt, width: 100%)[
    #text(size: 0.85em)[*Card* \ #q \ #a#if connects != none [ \ _Connects to:_ #connects]]
  ]
}
