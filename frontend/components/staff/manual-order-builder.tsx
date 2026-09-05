"use client";
import { useEffect, useMemo, useState } from "react";
import { ApiError, apiClient } from "../../lib/api";
import { useStaffAuth } from "../../lib/auth";
import { ActionButton, Dialog, FieldInput, Notice, SelectInput, TextArea } from "../ui";

type ModifierOption = { id: string; name: string; final_price_delta: number; available: boolean };
type ModifierGroup = { id: string; name: string; minimum_selections: number; maximum_selections: number; options: ModifierOption[] };
type MenuItem = { id: string; name: string; description: string; image_url?: string | null; item_type: "FOOD" | "DRINK"; final_base_price: number; available: boolean; category: { id: string; name: string }; modifier_groups: ModifierGroup[] };
type Table = { id: string; label: string; capacity: number; is_active: boolean };
type Catalog = { currency: string; tables: Table[]; menu: MenuItem[] };
type CartLine = { item: MenuItem; quantity: number; modifierOptionIds: string[] };
type StaffMember = { id: string; name: string; roles: string[] };

function money(value: number, currency: string) {
  return new Intl.NumberFormat("en-NG", { style: "currency", currency, maximumFractionDigits: 0 }).format(Number(value));
}

function modifierTotal(line: CartLine) {
  return line.item.modifier_groups.flatMap((group) => group.options)
    .filter((option) => line.modifierOptionIds.includes(option.id))
    .reduce((sum, option) => sum + Number(option.final_price_delta), 0);
}

export function ManualOrderBuilder({ locationId, enabled, onCreated }: { locationId: string; enabled: boolean; onCreated: () => Promise<void> }) {
  const { session } = useStaffAuth();
  const manager = session?.roles.includes("MANAGER") ?? false;
  const [open, setOpen] = useState(false);
  const [catalog, setCatalog] = useState<Catalog | null>(null);
  const [name, setName] = useState(""); const [phone, setPhone] = useState(""); const [email, setEmail] = useState(""); const [note, setNote] = useState("");
  const [takeaway, setTakeaway] = useState(false); const [tableId, setTableId] = useState(""); const [waiterId, setWaiterId] = useState(""); const [waiters, setWaiters] = useState<StaffMember[]>([]); const [cart, setCart] = useState<CartLine[]>([]);
  const [active, setActive] = useState<MenuItem | null>(null); const [selectedOptions, setSelectedOptions] = useState<string[]>([]); const [message, setMessage] = useState(""); const [pending, setPending] = useState(false);
  useEffect(() => {
    if (!open || !locationId || catalog) return;
    void apiClient.get<Catalog>(`/staff/locations/${encodeURIComponent(locationId)}/manual-order-catalog`)
      .then(setCatalog).catch((error) => setMessage(error instanceof Error ? error.message : "Could not load order choices."));
  }, [catalog, locationId, open]);
  useEffect(() => {
    if (!open || !manager || !locationId) return;
    void apiClient.get<StaffMember[]>(`/staff/members?location_id=${encodeURIComponent(locationId)}`)
      .then((members) => setWaiters(members.filter((member) => member.roles.includes("WAITER"))))
      .catch((error) => setMessage(error instanceof Error ? error.message : "Could not load assigned waiters."));
  }, [locationId, manager, open]);

  const categories = useMemo(() => [...new Map((catalog?.menu ?? []).map((item) => [item.category.id, item.category])).values()], [catalog]);
  const total = useMemo(() => cart.reduce((sum, line) => sum + (Number(line.item.final_base_price) + modifierTotal(line)) * line.quantity, 0), [cart]);
  const table = catalog?.tables.find((row) => row.id === tableId);

  function choose(item: MenuItem) { setMessage(""); setSelectedOptions([]); setActive(item); }
  function toggleOption(optionId: string, group: ModifierGroup) {
    setSelectedOptions((current) => {
      if (current.includes(optionId)) return current.filter((id) => id !== optionId);
      const outsideGroup = current.filter((id) => !group.options.some((option) => option.id === id));
      return group.maximum_selections === 1 ? [...outsideGroup, optionId] : [...current, optionId];
    });
  }
  function addToCart() {
    if (!active) return;
    const invalid = active.modifier_groups.find((group) => {
      const count = group.options.filter((option) => selectedOptions.includes(option.id)).length;
      return count < group.minimum_selections || count > group.maximum_selections;
    });
    if (invalid) { setMessage(`Choose ${invalid.minimum_selections} to ${invalid.maximum_selections} option(s) for ${invalid.name}.`); return; }
    setCart((current) => [...current, { item: active, quantity: 1, modifierOptionIds: selectedOptions }]); setActive(null);
  }
  async function create() {
    if (!name.trim() || !phone.trim() || !cart.length || (!takeaway && !tableId) || (manager && !waiterId)) { setMessage("Add a customer, choose a table for dine-in, assign a waiter, and add at least one menu item."); return; }
    setPending(true); setMessage("");
    try {
      await apiClient.post("/staff/orders/manual", {
        location_id: locationId, customer: { name: name.trim(), phone: phone.trim(), email: email.trim() || null }, service_mode: takeaway ? "TAKEAWAY" : "DINE_IN", table_id: takeaway ? null : tableId, waiter_id: manager ? waiterId : null,
        estimated_wait_minutes: 15, lines: cart.map((line) => ({ menu_item_id: line.item.id, quantity: line.quantity, modifier_option_ids: line.modifierOptionIds, special_instruction: note.trim() || null })),
      });
      setCart([]); setName(""); setPhone(""); setEmail(""); setNote(""); setTableId(""); setWaiterId(""); setMessage("Manual order created and accepted. It is now in preparation."); await onCreated();
    } catch (error) { setMessage(error instanceof ApiError ? error.message : "Manual order was not confirmed."); } finally { setPending(false); }
  }

  return <><section className="panel manual-order-builder"><div className="panel-heading"><div><h2>New staff order</h2><p>Choose the table and menu by name. Chowly keeps the IDs private.</p></div><ActionButton tone="quiet" onClick={() => setOpen((value) => !value)}>{open ? "Close" : "Create manual order"}</ActionButton></div>{open && <>
    <div className="inline-form"><FieldInput label="Customer name" value={name} onChange={(event) => setName(event.target.value)} required /><FieldInput label="Customer phone" type="tel" inputMode="tel" value={phone} onChange={(event) => setPhone(event.target.value)} required /><FieldInput label="Email (optional)" type="email" value={email} onChange={(event) => setEmail(event.target.value)} optional />{manager && <label className="field"><span>Assigned waiter</span><SelectInput value={waiterId} onChange={(event) => setWaiterId(event.target.value)} required><option value="">Choose an assigned waiter</option>{waiters.map((waiter) => <option key={waiter.id} value={waiter.id}>{waiter.name}</option>)}</SelectInput></label>}<label><input type="checkbox" checked={takeaway} onChange={(event) => setTakeaway(event.target.checked)} /> Takeaway</label>{!takeaway && <label className="field"><span>Table</span><SelectInput value={tableId} onChange={(event) => setTableId(event.target.value)}><option value="">Choose a table</option>{catalog?.tables.map((row) => <option key={row.id} value={row.id}>{row.label} · seats {row.capacity}{row.is_active ? " · active" : ""}</option>)}</SelectInput></label>}</div>
    {catalog ? <><div className="manual-order-heading"><div><p className="eyebrow">Menu</p><h3>{table ? `Order for ${table.label}` : takeaway ? "Takeaway order" : "Choose a table, then add a dish"}</h3></div><p>{cart.length} item{cart.length === 1 ? "" : "s"} · {money(total, catalog.currency)}</p></div><div className="manual-menu">{categories.map((category) => <section key={category.id}><h3>{category.name}</h3><div className="store-card-grid">{catalog.menu.filter((item) => item.category.id === category.id).map((item, index) => <article className={`store-card ${item.item_type === "DRINK" ? "drink-card" : ""}`} key={item.id}><button className="store-card-hit" onClick={() => choose(item)} disabled={!item.available}><div className="dish-art" aria-hidden="true"><span>{item.item_type === "DRINK" ? "✦" : ["✳", "✹", "✺"][index % 3]}</span><i /><b /></div><span className="card-copy"><small>{item.item_type === "DRINK" ? "From the bar" : "From the kitchen"}</small><b>{item.name}</b><span>{item.description || "Made fresh to order."}</span><strong>{money(item.final_base_price, catalog.currency)}</strong></span>{!item.available && <em>Sold out</em>}</button><button className="card-add" disabled={!item.available} onClick={() => choose(item)}>Add <span>+</span></button></article>)}</div></section>)}</div><section className="manual-cart"><h3>Order cart</h3>{cart.length ? <ul className="checkout-lines">{cart.map((line, index) => <li key={`${line.item.id}-${index}`}><span><b>{line.quantity} × {line.item.name}</b><small>{line.modifierOptionIds.map((id) => line.item.modifier_groups.flatMap((group) => group.options).find((option) => option.id === id)?.name).filter(Boolean).join(", ")}</small></span><b>{money((Number(line.item.final_base_price) + modifierTotal(line)) * line.quantity, catalog.currency)}</b><button onClick={() => setCart((current) => current.filter((_, position) => position !== index))}>Remove</button></li>)}</ul> : <p className="field-hint">Choose a menu card to start this order.</p>}<TextArea aria-label="Special instruction for this order" placeholder="Special instruction for this order (optional)" value={note} onChange={(event) => setNote(event.target.value)} maxLength={400} /><ActionButton tone="sun" pending={pending} disabled={!enabled || !cart.length || (!takeaway && !tableId) || (manager && !waiterId)} onClick={() => void create()}>Create order · {money(total, catalog.currency)}</ActionButton></section></> : <p className="loading">Loading tables and menu…</p>}
    {message && <Notice tone={message.includes("created") ? "success" : "info"} title="Manual order">{message}</Notice>}
  </>}</section><Dialog open={Boolean(active)} title={active?.name ?? "Menu item"} description={active ? `${active.item_type === "DRINK" ? "From the bar" : "From the kitchen"} · ${money(active.final_base_price, catalog?.currency ?? "NGN")}` : undefined} onClose={() => setActive(null)}>{active && <><p>{active.description || "Made fresh to order."}</p>{active.modifier_groups.map((group) => <fieldset key={group.id}><legend>{group.name} {group.minimum_selections ? `· choose ${group.minimum_selections}` : "· optional"}</legend>{group.options.map((option) => <label key={option.id}><input type={group.maximum_selections === 1 ? "radio" : "checkbox"} checked={selectedOptions.includes(option.id)} disabled={!option.available} onChange={() => toggleOption(option.id, group)} />{option.name}<span>{Number(option.final_price_delta) ? ` +${money(option.final_price_delta, catalog?.currency ?? "NGN")}` : ""}</span></label>)}</fieldset>)}{message && <p className="error" role="alert">{message}</p>}<ActionButton tone="sun" disabled={!active.available} onClick={addToCart}>Add to order · {money(active.final_base_price, catalog?.currency ?? "NGN")}</ActionButton></>}</Dialog></>;
}
