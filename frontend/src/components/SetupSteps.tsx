const STEPS = ['Add products', 'Review & publish', 'Go live'] as const

/** Seller setup progress (1-based), shown at the top of the setup pages. */
export function SetupSteps({ step }: { step: 1 | 2 | 3 }) {
  return (
    <ol className="steps setup-steps" aria-label="Shop setup progress">
      {STEPS.map((label, i) => {
        const n = i + 1
        const state = n === step ? 'current' : n < step ? 'done' : ''
        return (
          <li key={label} className={state} aria-current={n === step ? 'step' : undefined}>
            <span className="num">{n < step ? '✓' : n}</span>
            <span className="label">{label}</span>
          </li>
        )
      })}
    </ol>
  )
}
