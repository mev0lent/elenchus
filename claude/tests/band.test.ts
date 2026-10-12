import type { On } from 'claude-code'
import { expect, test } from 'claude-code/testing'

import { PALETTE, TONES, parse, view, sessionStatePath } from '../hooks/palette'

// What stands beneath the plugin in a session: the engine reading the file from disk and
// drawing nothing of its own in the band. A test answers both from memory.
function serve(on: On, read: () => string): void {
  on('session.id', () => ({ value: 'test-session' }) as never)
  on('session.root', () => ({ value: '/project' }) as never)
  on('fs.read', () => ({ value: read() }) as never)
  on('ui.render', () => ({ type: 'Box', props: {}, children: [] }) as never)
}

// WCAG relative luminance and contrast ratio, so a future palette edit that breaks
// readability fails here instead of in somebody's terminal.
function luminance(hex: string): number {
  const channel = (i: number) => {
    const c = parseInt(hex.slice(1 + i * 2, 3 + i * 2), 16) / 255
    return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4
  }

  return 0.2126 * channel(0) + 0.7152 * channel(1) + 0.0722 * channel(2)
}

function contrast(a: string, b: string): number {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x)

  return (hi! + 0.05) / (lo! + 0.05)
}

const BAND = {
  component: 'AbovePrompt',
  surface: 'terminal',
  props: {
    hasSurvey: false,
    isWorking: false,
    maxRows: 20,
    bodyColumns: 100,
    scroll: { offset: 0, bodyRows: 19 },
    view: {},
  },
} as const

function stateText(over: Record<string, unknown> = {}): string {
  return JSON.stringify({
    active: true,
    mode: 'explain',
    topic: 'TLS handshakes',
    phase: 'await_attempt',
    rounds: 0,
    violations: 0,
    ...over,
  })
}

test('every badge and the band text meet WCAG 4.5:1', async () => {
  for (const tone of Object.values(TONES)) {
    expect(contrast(tone.fg, tone.bg)).toBeGreaterThan(4.5)
  }

  expect(contrast(PALETTE.cream, PALETTE.navy)).toBeGreaterThan(4.5)
  expect(contrast(PALETTE.teal, PALETTE.navy)).toBeGreaterThan(4.5)
})

test('view maps every phase to a tone', async () => {
  const expected: Record<string, string> = {
    need_gate: 'locked',
    await_attempt: 'yours',
    challenging: 'yours',
    attempted: 'locked',
    review: 'locked',
    verdict_ok: 'yours',
    await_prediction: 'yours',
    run_open: 'open',
    await_reconcile: 'yours',
    open: 'open',
    idle: 'locked',
  }

  for (const [phase, tone] of Object.entries(expected)) {
    expect(view({ active: true, mode: 'explain', phase })?.tone).toBe(tone)
  }

  expect(view({ active: false, phase: 'open' })).toBeNull()
  expect(view({ active: true, mode: 'propose', phase: 'challenging', rounds: 1 })?.rounds).toBe('round 1/2')
  expect(view({ active: true, mode: 'predict', phase: 'run_open' })?.rounds).toBe('')
  expect(parse('{not json')).toBeNull()
  expect(parse('[]')).toBeNull()
  expect(parse('{"active":true,"focus_question":12}')).toBeNull()
  expect(parse('{"active":true,"violations":-1}')).toBeNull()
})

test('band draws the badge in the palette color for each tone', async ($, on) => {
  let text = stateText({ phase: 'idle' })
  serve(on, () => text)

  const cases: Array<[string, RegExp, string, string]> = [
    ['idle', /CLAUDE/, PALETTE.crimson, PALETTE.cream],
    ['await_attempt', /YOUR TURN/, PALETTE.purple, PALETTE.cream],
    ['open', /OPEN/, PALETTE.teal, PALETTE.navy],
  ]

  for (const [phase, label, bg, fg] of cases) {
    text = stateText({ phase })
    const ui = await $.ui.mount({ plugin: 'elenchus', ...BAND })
    const badge = await ui.find({ type: 'Text', text: label })

    expect(badge?.props.backgroundColor).toBe(bg)
    expect(badge?.props.color).toBe(fg)
    await ui.unmount()
  }
})

test('band shows mode, topic, round and violations', async ($, on) => {
  serve(on, () => stateText({ mode: 'propose', topic: 'note sync design', phase: 'challenging', rounds: 1, violations: 2 }))

  const ui = await $.ui.mount({ plugin: 'elenchus', ...BAND })

  expect(await ui.find({ type: 'Text', text: 'propose' })).toBeDefined()
  expect(await ui.find({ type: 'Text', text: /note sync design/ })).toBeDefined()
  expect(await ui.find({ type: 'Text', text: /round 1\/2/ })).toBeDefined()
  expect((await ui.find({ type: 'Text', text: /Rule violations: 2/ }))?.props.backgroundColor).toBe(PALETTE.crimson)
  await ui.unmount()
})

test('band draws nothing when Elenchus is off, unreadable or empty', async ($, on) => {
  let text = ''
  serve(on, () => text)

  for (const t of ['', '{broken', stateText({ active: false })]) {
    text = t
    const ui = await $.ui.mount({ plugin: 'elenchus', ...BAND })

    expect(await ui.find({ type: 'Text', text: /CLAUDE|YOUR TURN|OPEN/ })).toBeUndefined()
    await ui.unmount()
  }
})

test('focus question stays visible on a narrow terminal without the extra footer', async ($, on) => {
  serve(on, () => stateText({ phase: 'challenging', focus_question: 'Warum verhindert ein Zertifikat allein noch keinen Angriff?', help_level: 1 }))
  const ui = await $.ui.mount({ plugin: 'elenchus', ...BAND, props: { ...BAND.props, bodyColumns: 38, maxRows: 6 } })
  expect((await ui.find({ type: 'Text', text: /Warum verhindert/ }))?.props.bold).toBe(true)
  expect(await ui.find({ type: 'Text', text: /shows tool details/ })).toBeUndefined()
  expect(await ui.find({ type: 'Text', text: /answer the challenge/ })).toBeDefined()
  await ui.unmount()
})

test('review shows Claude judging and removes the stale learner question', async ($, on) => {
  serve(on, () => stateText({ phase: 'review', focus_question: 'Old question?' }))
  const ui = await $.ui.mount({ plugin: 'elenchus', ...BAND })
  expect(await ui.find({ type: 'Text', text: /CLAUDE/ })).toBeDefined()
  expect(await ui.find({ type: 'Text', text: /Old question/ })).toBeUndefined()
  await ui.unmount()
})

test('state lookup uses this session and the same safe key as Python', async ($, on) => {
  const paths: string[] = []
  on('session.id', () => ({ value: 'test-session' }) as never)
  on('session.root', () => ({ value: '/project' }) as never)
  on('fs.read', (_, e) => { paths.push(e.path); return { value: stateText() } as never })
  on('ui.render', () => ({ type: 'Box', props: {}, children: [] }) as never)
  const ui = await $.ui.mount({ plugin: 'elenchus', ...BAND })
  expect(paths[0]?.replace(/\\/g, '/').endsWith('/project/.elenchus/sessions/s-746573742d73657373696f6e/state.json')).toBe(true)
  expect(sessionStatePath('C:\\project', 'one')).toBe('C:/project/.elenchus/sessions/s-6f6e65/state.json')
  await ui.unmount()
})

test('only successful internal calls are compacted; full mode, errors and runs stay visible', async ($, on) => {
  let text = stateText()
  on('session.id', () => ({ value: 'test-session' }) as never)
  on('session.root', () => ({ value: '/project' }) as never)
  on('fs.read', () => ({ value: text }) as never)
  on('ui.render', () => ({ type: 'Text', props: {}, children: ['Original tool output'] }) as never)
  const call = {
    tool_use_id: 'call-1', tool: 'Bash', input: { command: 'python "/plugin/scripts/elenchus.py" --session "test-session" challenge --text "Why?"' },
    isRunning: false, isErrored: false, isInterrupted: false,
  }
  const compact = await $.ui.mount({ plugin: 'elenchus', component: 'ToolUse', surface: 'terminal', props: call })
  expect(await compact.find({ type: 'Text', text: /Elenchus · challenge/ })).toBeDefined()
  await compact.unmount()
  const hidden = await $.ui.mount({ plugin: 'elenchus', component: 'ToolResult', surface: 'terminal', props: { tool_use_id: 'call-1', tool: 'Bash', output: {}, isErrored: false } })
  expect(await hidden.find({ type: 'Text', text: /Original/ })).toBeUndefined()
  await hidden.unmount()
  for (const props of [
    { ...call, isErrored: true },
    { ...call, isInterrupted: true },
    { ...call, input: { command: 'python "/plugin/scripts/elenchus.py" --session "test-session" run' } },
    { ...call, input: { command: 'git status' } },
  ]) {
    const ui = await $.ui.mount({ plugin: 'elenchus', component: 'ToolUse', surface: 'terminal', props })
    expect(await ui.find({ type: 'Text', text: /Original tool output/ })).toBeDefined()
    await ui.unmount()
  }
  text = stateText({ ui_details: true })
  const full = await $.ui.mount({ plugin: 'elenchus', component: 'ToolUse', surface: 'terminal', props: call })
  expect(await full.find({ type: 'Text', text: /Original tool output/ })).toBeDefined()
  await full.unmount()
})
