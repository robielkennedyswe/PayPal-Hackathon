// Screen 2: edit each AI draft, see the agent-facing JSON live, publish.
// Fields save on blur; Publish saves anything still pending first.

import { useEffect, useMemo, useState } from 'react'
import { agentView } from '../agentView'
import { api } from '../api'
import { Link } from '../components/Link'
import { navigate } from '../router'
import { SetupSteps } from '../components/SetupSteps'
import { TopBar } from '../components/TopBar'
import { rememberShop } from '../myShops'
import { normalizePrice, type Product, type ProductUpdate, type Shop } from '../types'

/** Form values are strings while editing; parsed and validated on save. */
type Form = { title: string; description: string; price: string; stock: string; tags: string }
type Field = keyof Form
type SaveState = 'idle' | 'saving' | 'saved' | 'error'

const toForm = (p: Product): Form => ({
  title: p.title,
  description: p.description,
  price: p.price,
  stock: String(p.stock),
  tags: p.tags.join(', '),
})

const parseTags = (s: string) =>
  s
    .split(',')
    .map((t) => t.trim())
    .filter(Boolean)

/** Same rules as backend/app/schemas.py ProductUpdate. Returns field -> message. */
function validate(f: Form): Partial<Record<Field, string>> {
  const e: Partial<Record<Field, string>> = {}
  if (f.title.trim().length < 3 || f.title.length > 120) e.title = '3–120 characters'
  if (f.description.trim().length < 10 || f.description.length > 2000) e.description = '10–2000 characters'
  const price = normalizePrice(f.price)
  if (price === null) e.price = 'Use a price like 20 or 34.50'
  else if (Number(price) <= 0) e.price = 'Price must be more than $0'
  if (!/^\d+$/.test(f.stock) || Number(f.stock) > 100_000) e.stock = 'Whole number, 0 or more'
  if (parseTags(f.tags).length > 15) e.tags = 'At most 15 tags'
  return e
}

/** Only the fields that differ from the saved product, in API shape. */
function changes(form: Form, p: Product): ProductUpdate {
  const c: ProductUpdate = {}
  if (form.title.trim() !== p.title) c.title = form.title.trim()
  if (form.description.trim() !== p.description) c.description = form.description.trim()
  const price = normalizePrice(form.price) ?? form.price
  if (price !== p.price) c.price = price
  if (Number(form.stock) !== p.stock) c.stock = Number(form.stock)
  const tags = parseTags(form.tags)
  if (tags.join('\n') !== p.tags.join('\n')) c.tags = tags
  return c
}

export function Review({ shopId }: { shopId: string }) {
  const [shop, setShop] = useState<Shop | null>(null)
  const [products, setProducts] = useState<Product[]>([])
  const [forms, setForms] = useState<Record<string, Form>>({})
  const [saveState, setSaveState] = useState<Record<string, SaveState>>({})
  const [saveError, setSaveError] = useState<Record<string, string>>({})
  const [selected, setSelected] = useState<string | null>(null)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [publishing, setPublishing] = useState(false)
  const [publishError, setPublishError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    api
      .getShop(shopId)
      .then((s) => {
        if (cancelled) return
        setShop(s)
        rememberShop(s.id, s.name)
        setProducts(s.products)
        setForms(Object.fromEntries(s.products.map((p) => [p.id, toForm(p)])))
        setSelected(s.products[0]?.id ?? null)
      })
      .catch((e: Error) => !cancelled && setLoadError(e.message))
    return () => {
      cancelled = true
    }
  }, [shopId])

  const errors = useMemo(
    () => Object.fromEntries(Object.entries(forms).map(([id, f]) => [id, validate(f)])),
    [forms],
  )
  const anyInvalid = Object.values(errors).some((e) => Object.keys(e).length > 0)

  const setField = (id: string, field: Field, value: string) =>
    setForms((fs) => ({ ...fs, [id]: { ...fs[id], [field]: value } }))

  /** PATCH whatever changed for one product. Returns false on failure. */
  async function save(id: string): Promise<boolean> {
    const product = products.find((p) => p.id === id)
    const form = forms[id]
    if (!product || !form || Object.keys(validate(form)).length > 0) return false
    const diff = changes(form, product)
    if (Object.keys(diff).length === 0) return true
    setSaveState((s) => ({ ...s, [id]: 'saving' }))
    try {
      const updated = await api.updateProduct(id, diff)
      setProducts((ps) => ps.map((p) => (p.id === id ? updated : p)))
      setSaveState((s) => ({ ...s, [id]: 'saved' }))
      setSaveError((s) => ({ ...s, [id]: '' }))
      return true
    } catch (e) {
      setSaveState((s) => ({ ...s, [id]: 'error' }))
      setSaveError((s) => ({ ...s, [id]: (e as Error).message }))
      return false
    }
  }

  async function remove(id: string) {
    const p = products.find((x) => x.id === id)
    if (!p || !window.confirm(`Remove "${p.title}"?`)) return
    try {
      await api.deleteProduct(id)
    } catch (e) {
      setSaveError((s) => ({ ...s, [id]: (e as Error).message }))
      return
    }
    const rest = products.filter((x) => x.id !== id)
    setProducts(rest)
    if (selected === id) setSelected(rest[0]?.id ?? null)
  }

  async function publish() {
    setPublishing(true)
    setPublishError(null)
    const results = await Promise.all(products.map((p) => save(p.id)))
    if (results.every(Boolean)) {
      try {
        await api.publishShop(shopId)
        navigate(`/sell/${shopId}/dashboard`) // step 3: go live
      } catch (e) {
        setPublishError((e as Error).message)
      }
    } else {
      setPublishError('Some changes could not be saved. Fix them and try again.')
    }
    setPublishing(false)
  }

  if (loadError) {
    return (
      <>
        <TopBar />
        <main className="page">
          <div className="banner banner-error">Couldn't load this shop: {loadError}</div>
          <Link href="/sell" className="btn">
            Start a new shop
          </Link>
        </main>
      </>
    )
  }
  if (!shop) {
    return (
      <>
        <TopBar />
        <main className="page muted">Loading…</main>
      </>
    )
  }

  const sel = products.find((p) => p.id === selected)
  const selForm = sel && forms[sel.id]

  return (
    <>
      <TopBar />
      <main className="page">
        <SetupSteps step={shop.published ? 3 : 2} />
        <div className="page-head">
          <div>
            <Link href={`/sell/${shopId}`} className="back-link">
              ← Add more photos
            </Link>
            <h1>Review &amp; publish</h1>
            <p>
              Check each AI draft for <strong>{shop.name}</strong>. Changes save when you leave a field.
            </p>
          </div>
          <div className="head-actions">
            {shop.published && (
              <Link href={`/sell/${shopId}/dashboard`} className="btn">
                Dashboard
              </Link>
            )}
            <button
              className="btn btn-primary"
              onClick={publish}
              // Not disabled while a field is saving: clicking Publish blurs the
              // field, which starts a save, and a button that disables itself
              // mid-click swallows the click. publish() saves pending edits itself.
              disabled={shop.published || publishing || anyInvalid || products.length === 0}
            >
              {shop.published ? 'Published ✓' : publishing ? 'Publishing…' : 'Publish to AI agents'}
            </button>
          </div>
        </div>

        {shop.published && (
          <div className="banner banner-success" role="status">
            <div>
              <strong>{shop.name} is live to AI agents.</strong>
              <div>Edits you make now go live as soon as they save.</div>
            </div>
            <Link href={`/sell/${shopId}/dashboard`} className="btn btn-primary btn-sm">
              Open your dashboard →
            </Link>
          </div>
        )}
        {publishError && <div className="banner banner-error">{publishError}</div>}
        {anyInvalid && !shop.published && (
          <div className="banner banner-error">Fix the highlighted fields before publishing.</div>
        )}

        {products.length === 0 ? (
          <div className="card card-pad">
            <p className="muted" style={{ marginBottom: 16 }}>
              No products yet.
            </p>
            <Link href={`/sell/${shopId}`} className="btn">
              Add photos
            </Link>
          </div>
        ) : (
          <div className="review-grid">
            <div className="review-list">
              {products.map((p) => (
                <ProductEditor
                  key={p.id}
                  product={p}
                  form={forms[p.id]}
                  errors={errors[p.id] ?? {}}
                  saveState={saveState[p.id] ?? 'idle'}
                  saveError={saveError[p.id]}
                  selected={p.id === selected}
                  onSelect={() => setSelected(p.id)}
                  onChange={(field, value) => setField(p.id, field, value)}
                  onBlur={(field) => {
                    // Show "20" as "20.00" once the seller leaves the field.
                    const price = normalizePrice(forms[p.id].price)
                    if (field === 'price' && price) setField(p.id, 'price', price)
                    save(p.id)
                  }}
                  onRemove={() => remove(p.id)}
                />
              ))}
            </div>

            <aside className="agent-panel" aria-label="What AI agents will see">
              <div className="agent-panel-head">
                <span className="chip agent">agent view</span>
                <h2>What AI agents will see</h2>
                <p>
                  Returned by the <code>get_product</code> MCP tool{sel ? ` for “${sel.title}”` : ''}. Updates as
                  you type.
                </p>
              </div>
              {sel && selForm && (
                <pre className="agent-json">
                  {JSON.stringify(
                    agentView(
                      sel.id,
                      {
                        title: selForm.title.trim(),
                        description: selForm.description.trim(),
                        price: normalizePrice(selForm.price) ?? selForm.price,
                        stock: Number(selForm.stock) || 0,
                        tags: parseTags(selForm.tags),
                        attributes: sel.attributes,
                      },
                      shop,
                    ),
                    null,
                    2,
                  )}
                </pre>
              )}
            </aside>
          </div>
        )}
      </main>
    </>
  )
}

type EditorProps = {
  product: Product
  form: Form
  errors: Partial<Record<Field, string>>
  saveState: SaveState
  saveError?: string
  selected: boolean
  onSelect: () => void
  onChange: (field: Field, value: string) => void
  onBlur: (field: Field) => void
  onRemove: () => void
}

function ProductEditor({ product: p, form, errors, saveState, saveError, selected, onSelect, onChange, onBlur, onRemove }: EditorProps) {
  const id = (f: Field) => `${p.id}-${f}`
  const input = (f: Field, label: string, extra?: { prefix?: string; inputMode?: 'decimal' | 'numeric'; hint?: string }) => (
    <div className="field">
      <label htmlFor={id(f)}>{label}</label>
      <div className={extra?.prefix ? 'input-prefix' : undefined}>
        {extra?.prefix && <span aria-hidden="true">{extra.prefix}</span>}
        <input
          id={id(f)}
          className="input"
          value={form[f]}
          inputMode={extra?.inputMode}
          onChange={(e) => onChange(f, e.target.value)}
          onBlur={() => onBlur(f)}
          aria-invalid={!!errors[f]}
          aria-describedby={errors[f] ? `${id(f)}-err` : undefined}
        />
      </div>
      {errors[f] ? (
        <span id={`${id(f)}-err`} className="error-text">
          {errors[f]}
        </span>
      ) : (
        extra?.hint && <span className="hint">{extra.hint}</span>
      )}
    </div>
  )

  return (
    <article className={`card editor${selected ? ' selected' : ''}`} onFocusCapture={onSelect} onClick={onSelect}>
      <div className="editor-img">{p.image_url && <img src={p.image_url} alt="" />}</div>
      <div className="editor-fields">
        <div className="editor-top">
          <span className="chip seller">AI draft</span>
          <span className={`save-state ${saveState}`} aria-live="polite">
            {saveState === 'saving' ? 'Saving…' : saveState === 'saved' ? 'Saved' : saveState === 'error' ? 'Not saved' : ''}
          </span>
        </div>
        {input('title', 'Title')}
        <div className="field">
          <label htmlFor={id('description')}>Description</label>
          <textarea
            id={id('description')}
            className="input"
            rows={3}
            value={form.description}
            onChange={(e) => onChange('description', e.target.value)}
            onBlur={() => onBlur('description')}
            aria-invalid={!!errors.description}
          />
          {errors.description && <span className="error-text">{errors.description}</span>}
        </div>
        <div className="editor-row">
          {input('price', 'Price (USD)', { prefix: '$', inputMode: 'decimal', hint: 'AI suggested · whole dollars are fine' })}
          {input('stock', 'Stock', { inputMode: 'numeric' })}
        </div>
        {input('tags', 'Tags', { hint: 'Comma-separated; agents search these' })}
        {saveError && <div className="draft-error">{saveError}</div>}
        <div className="draft-actions">
          <button className="btn-danger-text" onClick={onRemove}>
            Remove product
          </button>
        </div>
      </div>
    </article>
  )
}
