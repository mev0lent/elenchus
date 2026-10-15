// Single source of truth for the Elenchus colors. anki/elenchus-card.css repeats the same
// hex values by hand, and tests/test_palette.py fails if the two ever drift apart.
//
// Contrast (WCAG), measured on the palette:
//   cream on navy 19.0, teal on navy 10.4, navy on teal 10.4, cream on crimson 5.2, cream on purple 5.0
//   purple on navy 3.8 and crimson on navy 3.7 FAIL for small text: use them only as a
//   badge background or as decoration, never as small text on navy.

export const PALETTE = {
  cream: '#FBF5F3',
  purple: '#7D5BA6',
  navy: '#000022',
  teal: '#3BCEAC',
  crimson: '#C42847',
} as const

export type Tone = 'locked' | 'yours' | 'open'

export const TONES: Record<Tone, { bg: string; fg: string; label: string }> = {
  locked: { bg: PALETTE.crimson, fg: PALETTE.cream, label: 'CLAUDE' },
  yours: { bg: PALETTE.purple, fg: PALETTE.cream, label: 'YOUR TURN' },
  open: { bg: PALETTE.teal, fg: PALETTE.navy, label: 'OPEN' },
}

export type GateState = {
  active?: boolean
  mode?: string | null
  topic?: string
  phase?: string
  rounds?: number
  violations?: number
  focus_question?: string
  help_level?: number
  ui_details?: boolean
}

export type View = {
  tone: Tone
  hint: string
  mode: string
  topic: string
  rounds: string
  violations: number
  question: string
  support: string
}

const MIN_ROUNDS: Record<string, number> = { explain: 1, propose: 2 }

export function parse(text: string): GateState | null {
  try {
    const value = JSON.parse(text)
    if (value === null || typeof value !== 'object' || Array.isArray(value)) return null
    const s = value as GateState
    if (typeof s.active !== 'boolean') return null
    for (const key of ['mode', 'topic', 'phase', 'focus_question'] as const) {
      if (s[key] !== undefined && s[key] !== null && typeof s[key] !== 'string') return null
    }
    for (const key of ['rounds', 'violations', 'help_level'] as const) {
      if (s[key] !== undefined && (typeof s[key] !== 'number' || !Number.isFinite(s[key]) || s[key]! < 0)) return null
    }
    return s
  } catch {
    return null
  }
}

export function view(state: GateState): View | null {
  if (state.active !== true) {
    return null
  }

  const mode = state.mode ?? ''
  const phase = state.phase ?? 'idle'
  let tone: Tone = 'locked'
  let hint = 'start the next topic when you are ready'

  switch (phase) {
    case 'need_gate':
      hint = 'Claude has to pick a mode first'
      break
    case 'await_attempt':
      tone = 'yours'
      hint = mode === 'propose' ? 'propose your idea first' : 'explain it in your own words'
      break
    case 'challenging':
      tone = 'yours'
      hint = 'answer the challenge'
      break
    case 'attempted':
    case 'review':
      hint = 'Claude is judging your answer'
      break
    case 'verdict_ok':
      tone = 'yours'
      hint = 'reflect: your conclusion and reasons; disagreement is welcome'
      break
    case 'await_prediction':
      tone = 'yours'
      hint = 'type predict: before anything runs'
      break
    case 'run_open':
      tone = 'open'
      hint = 'Claude runs your registered example once'
      break
    case 'await_reconcile':
      tone = 'yours'
      hint = 'reflect: what differed and why'
      break
    case 'open':
      tone = 'open'
      hint = 'one turn of work, then it locks again'
      break
    default:
      break
  }

  const need = MIN_ROUNDS[mode]

  return {
    tone,
    hint,
    mode: mode === '' ? 'auto' : mode,
    topic: clean(state.topic ?? ''),
    rounds: need === undefined ? '' : `round ${state.rounds ?? 0}/${need}`,
    violations: state.violations ?? 0,
    question: tone === 'yours' ? clean(state.focus_question ?? '') : '',
    support: state.help_level === 2 ? 'minimal hint' : state.help_level === 1 ? 'smaller question' : '',
  }
}

export function clean(text: string): string {
  return text.replace(/[\u0000-\u0008\u000b-\u001f\u007f]/g, '').trim()
}

// Same byte-hex encoding as the Python engine, with no path separators.
export function sessionStatePath(root: string, id: string): string {
  const key = Array.from(new TextEncoder().encode(id), b => b.toString(16).padStart(2, '0')).join('')
  return `${root.replace(/\\/g, '/').replace(/\/$/, '')}/.elenchus/sessions/s-${key}/state.json`
}
