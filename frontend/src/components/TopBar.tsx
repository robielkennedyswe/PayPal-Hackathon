import { Link } from './Link'

const STEPS = ['Add products', 'Review & publish', 'Go live'] as const

/** Brand bar; shows the seller progress steps when `step` is given (1-based). */
export function TopBar({ step }: { step?: 1 | 2 | 3 }) {
  return (
    <header className="topbar">
      <div className="topbar-inner">
        <Link href="/" className="brand-link">
          <img src="/favicon.svg" alt="" />
          ShopMCP
        </Link>
        {step && (
          <ol className="steps" aria-label="Seller setup progress">
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
        )}
      </div>
    </header>
  )
}
