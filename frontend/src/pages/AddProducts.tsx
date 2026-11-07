// Screen 1: shop details + photo drop zone. Each photo becomes an AI-drafted
// listing card as soon as the backend returns it.

import { useEffect, useRef, useState, type DragEvent, type KeyboardEvent } from 'react'
import { api } from '../api'
import { Link } from '../components/Link'
import { TopBar } from '../components/TopBar'
import { navigate } from '../router'
import { EMAIL_RE, type Product, type Shop } from '../types'

type Draft = {
  key: string
  preview: string // local object URL while uploading, server image_url once loaded
  status: 'queued' | 'drafting' | 'done' | 'error'
  file?: File // kept so a failed upload can be retried
  product?: Product
  error?: string
}

const ACCEPT = ['image/jpeg', 'image/png', 'image/webp', 'image/gif']
const MAX_BYTES = 5 * 1024 * 1024 // matches the backend cap
const CONCURRENCY = 3 // parallel uploads; keeps the real AI API under rate limits later

export function AddProducts({ shopId }: { shopId?: string }) {
  const [shop, setShop] = useState<Shop | null>(null)
  const [name, setName] = useState('')
  const [email, setEmail] = useState('')
  const [touched, setTouched] = useState(false)
  const [drafts, setDrafts] = useState<Draft[]>([])
  const [formError, setFormError] = useState<string | null>(null)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [dragging, setDragging] = useState(false)

  // Refs hold values that async upload callbacks need without re-rendering.
  const inputRef = useRef<HTMLInputElement>(null)
  const shopRef = useRef<Shop | null>(null)
  const creating = useRef<Promise<Shop> | null>(null)
  const queue = useRef<{ key: string; file: File }[]>([])
  const active = useRef(0)
  const objectUrls = useRef<string[]>([])

  // Arriving at /sell/:shopId (refresh, back button): load the shop and its
  // products. Skipped right after we created the shop ourselves.
  useEffect(() => {
    if (!shopId || shopRef.current?.id === shopId) return
    let cancelled = false
    api
      .getShop(shopId)
      .then((s) => {
        if (cancelled) return
        shopRef.current = s
        setShop(s)
        setName(s.name)
        setEmail(s.paypal_payee_email)
        setDrafts(s.products.map((p) => ({ key: p.id, preview: p.image_url ?? '', status: 'done', product: p })))
      })
      .catch((e: Error) => !cancelled && setLoadError(e.message))
    return () => {
      cancelled = true
    }
  }, [shopId])

  // Free the in-memory image previews when leaving the page.
  useEffect(() => {
    const urls = objectUrls.current
    return () => urls.forEach((u) => URL.revokeObjectURL(u))
  }, [])

  const nameOk = name.trim().length > 0
  const emailOk = EMAIL_RE.test(email.trim())
  const formReady = shop !== null || (nameOk && emailOk)

  const update = (key: string, patch: Partial<Draft>) =>
    setDrafts((ds) => ds.map((d) => (d.key === key ? { ...d, ...patch } : d)))

  /** Create the shop on the first upload; concurrent callers share one request. */
  function ensureShop(): Promise<Shop> {
    if (shopRef.current) return Promise.resolve(shopRef.current)
    creating.current ??= api
      .createShop(name.trim(), email.trim())
      .then((s) => {
        shopRef.current = s
        setShop(s)
        setFormError(null)
        // Put the shop id in the URL so a refresh resumes this shop.
        navigate(`/sell/${s.id}`, { replace: true })
        return s
      })
      .finally(() => {
        creating.current = null
      })
    return creating.current
  }

  /** Start queued uploads, at most CONCURRENCY at a time. */
  function pump(id: string) {
    while (active.current < CONCURRENCY && queue.current.length > 0) {
      const job = queue.current.shift()!
      active.current++
      update(job.key, { status: 'drafting' })
      api
        .uploadPhoto(id, job.file)
        .then((product) => update(job.key, { status: 'done', product, error: undefined }))
        .catch((e: Error) => update(job.key, { status: 'error', error: e.message }))
        .finally(() => {
          active.current--
          pump(id)
        })
    }
  }

  async function enqueue(jobs: { key: string; file: File }[]) {
    if (jobs.length === 0) return
    let s: Shop
    try {
      s = await ensureShop()
    } catch (e) {
      const message = (e as Error).message
      setFormError(message)
      jobs.forEach((j) => update(j.key, { status: 'error', error: 'Shop could not be created' }))
      return
    }
    queue.current.push(...jobs)
    pump(s.id)
  }

  function addFiles(files: File[]) {
    if (!formReady) {
      setTouched(true)
      return
    }
    const fresh: Draft[] = files.map((file) => {
      // Only preview real images (a rejected .txt would show a broken icon).
      const preview = ACCEPT.includes(file.type) ? URL.createObjectURL(file) : ''
      if (preview) objectUrls.current.push(preview)
      // Check type and size here so the seller gets instant feedback.
      const error = !ACCEPT.includes(file.type)
        ? 'Use a JPG, PNG, WebP or GIF image'
        : file.size > MAX_BYTES
          ? 'Image is over 5 MB'
          : undefined
      return { key: crypto.randomUUID(), preview, file, status: error ? 'error' : 'queued', error }
    })
    setDrafts((ds) => [...ds, ...fresh])
    enqueue(fresh.filter((d) => d.status === 'queued').map((d) => ({ key: d.key, file: d.file! })))
  }

  function retry(d: Draft) {
    if (!d.file) return
    update(d.key, { status: 'queued', error: undefined })
    enqueue([{ key: d.key, file: d.file }])
  }

  async function remove(d: Draft) {
    if (d.product) {
      try {
        await api.deleteProduct(d.product.id)
      } catch (e) {
        update(d.key, { error: (e as Error).message })
        return
      }
    }
    setDrafts((ds) => ds.filter((x) => x.key !== d.key))
  }

  // ---- drop zone handlers ----
  const openPicker = () => (formReady ? inputRef.current?.click() : setTouched(true))
  const onDrop = (e: DragEvent) => {
    e.preventDefault()
    setDragging(false)
    addFiles(Array.from(e.dataTransfer.files))
  }
  const onKeyDown = (e: KeyboardEvent) => {
    if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault()
      openPicker()
    }
  }

  const ready = drafts.filter((d) => d.status === 'done').length
  const busy = drafts.some((d) => d.status === 'queued' || d.status === 'drafting')

  if (loadError) {
    return (
      <>
        <TopBar step={1} />
        <main className="page">
          <div className="banner banner-error">Couldn't load this shop: {loadError}</div>
          <Link href="/sell" className="btn">
            Start a new shop
          </Link>
        </main>
      </>
    )
  }

  return (
    <>
      <TopBar step={1} />
      <main className="page">
        <div className="page-head">
          <div>
            <h1>Add your products</h1>
            <p>Drop in product photos. AI drafts each listing; you review everything before it goes live.</p>
          </div>
        </div>

        <div className="add-grid">
          <section className="card card-pad shop-form" aria-labelledby="shop-heading">
            <h2 id="shop-heading">Your shop</h2>
            <div className="field">
              <label htmlFor="shop-name">Shop name</label>
              <input
                id="shop-name"
                className="input"
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="e.g. Clay Corner"
                maxLength={80}
                disabled={shop !== null}
                aria-invalid={touched && !nameOk}
              />
              {touched && !nameOk && <span className="error-text">Enter a shop name</span>}
            </div>
            <div className="field">
              <label htmlFor="shop-email">PayPal sandbox business email</label>
              <input
                id="shop-email"
                className="input"
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="you@business.example.com"
                disabled={shop !== null}
                aria-invalid={touched && !emailOk}
              />
              {touched && !emailOk ? (
                <span className="error-text">Enter a valid email</span>
              ) : (
                <span className="hint">Payments from AI-agent sales go to this PayPal account.</span>
              )}
            </div>
            {formError && <div className="banner banner-error">{formError}</div>}
            {shop && (
              <p className="locked-note">
                Shop created · <span className="mono">{shop.slug}</span>
              </p>
            )}
          </section>

          <section aria-label="Product photos">
            <div
              className={`dropzone${dragging ? ' dragging' : ''}`}
              role="button"
              tabIndex={0}
              aria-disabled={!formReady}
              onClick={openPicker}
              onKeyDown={onKeyDown}
              onDragOver={(e) => {
                e.preventDefault()
                setDragging(true)
              }}
              onDragLeave={() => setDragging(false)}
              onDrop={onDrop}
            >
              <span className="dropzone-icon" aria-hidden="true">
                <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <rect x="3" y="5" width="18" height="14" rx="2" />
                  <circle cx="9" cy="11" r="2" />
                  <path d="m21 17-5-5-8 7" />
                </svg>
              </span>
              <strong>Drop product photos here</strong>
              <span className="muted">
                {formReady ? 'or click to choose · JPG, PNG, WebP · up to 5 MB each' : 'Fill in your shop details first'}
              </span>
              <input
                ref={inputRef}
                type="file"
                accept={ACCEPT.join(',')}
                multiple
                hidden
                onChange={(e) => {
                  addFiles(Array.from(e.target.files ?? []))
                  e.target.value = '' // allow choosing the same file again
                }}
              />
            </div>

            {drafts.length > 0 && (
              <div className="drafts" aria-live="polite">
                {drafts.map((d) => (
                  <DraftCard key={d.key} draft={d} onRetry={() => retry(d)} onRemove={() => remove(d)} />
                ))}
              </div>
            )}
          </section>
        </div>

        <div className="footer-bar">
          <span className="muted">
            {busy ? 'AI is drafting listings…' : `${ready} listing${ready === 1 ? '' : 's'} ready`}
          </span>
          <button
            className="btn btn-primary"
            disabled={!shop || ready === 0 || busy}
            onClick={() => shop && navigate(`/sell/${shop.id}/review`)}
          >
            Review &amp; publish →
          </button>
        </div>
      </main>
    </>
  )
}

function DraftCard({ draft: d, onRetry, onRemove }: { draft: Draft; onRetry: () => void; onRemove: () => void }) {
  const working = d.status === 'queued' || d.status === 'drafting'
  return (
    <article className="card draft" aria-busy={working}>
      <div className={`draft-img${working ? ' drafting' : ''}`}>
        {d.preview && <img src={d.preview} alt={d.product?.title ?? 'Uploaded product photo'} />}
        {d.status === 'done' && <span className="chip seller">AI draft</span>}
      </div>
      <div className="draft-body">
        {working && (
          <>
            <span className="muted" style={{ fontSize: 13 }}>
              {d.status === 'queued' ? 'Queued…' : 'AI is drafting the listing…'}
            </span>
            <div className="skeleton-line" style={{ width: '85%' }} />
            <div className="skeleton-line" style={{ width: '40%' }} />
          </>
        )}
        {d.status === 'done' && d.product && (
          <>
            <h3>{d.product.title}</h3>
            <span className="draft-price">${d.product.price}</span>
            <div className="tags">
              {d.product.tags.slice(0, 3).map((t) => (
                <span key={t} className="tag">
                  {t}
                </span>
              ))}
            </div>
            {d.error && <span className="draft-error">{d.error}</span>}
            <div className="draft-actions">
              <button className="btn-danger-text" onClick={onRemove}>
                Remove
              </button>
            </div>
          </>
        )}
        {d.status === 'error' && (
          <>
            <span className="draft-error">{d.error}</span>
            <div className="draft-actions">
              {d.file && ACCEPT.includes(d.file.type) && d.file.size <= MAX_BYTES && (
                <button className="btn btn-sm" onClick={onRetry}>
                  Retry
                </button>
              )}
              <button className="btn-danger-text" onClick={onRemove}>
                Remove
              </button>
            </div>
          </>
        )}
      </div>
    </article>
  )
}
