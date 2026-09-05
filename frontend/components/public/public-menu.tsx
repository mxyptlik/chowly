"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { apiClient } from "../../lib/api";
import { getPublicCached } from "../../lib/public-cache";
import { PublicHeader, PublicShell, type PublicLocation, type PublicRestaurant } from "./public-restaurant";

type MenuItem = { name: string; description?: string | null; item_type?: "FOOD" | "DRINK"; price: string | number; currency?: string; available?: boolean };
type MenuCategory = { name: string; items: MenuItem[] };
type Response = { restaurant: PublicRestaurant; location: PublicLocation; menu: MenuCategory[] };
function money(value: string | number, currency = "NGN") { return new Intl.NumberFormat("en-NG", { style: "currency", currency, maximumFractionDigits: 0 }).format(Number(value)); }

/** Browse-only by design: table QR capability is never accepted on this route. */
export function PublicMenu({ tenantSlug, locationSlug }: { tenantSlug: string; locationSlug: string }) {
  const [data, setData] = useState<Response | null>(null); const [error, setError] = useState(false); const [filter, setFilter] = useState<"ALL" | "FOOD" | "DRINK">("ALL");
  useEffect(() => { void getPublicCached(`restaurant-menu:${tenantSlug}:${locationSlug}`, () => apiClient.get<Response>(`/public/restaurants/${encodeURIComponent(tenantSlug)}/locations/${encodeURIComponent(locationSlug)}`)).then(setData).catch(() => setError(true)); }, [tenantSlug, locationSlug]);
  const categories = useMemo(() => data?.menu.map(category => ({ ...category, items: category.items.filter(item => filter === "ALL" || item.item_type === filter) })).filter(category => category.items.length) ?? [], [data, filter]);
  if (error) return <PublicShell><PublicHeader /><section className="public-menu-state"><h1>Menu unavailable.</h1><Link href={`/r/${tenantSlug}/${locationSlug}`}>Back to location</Link></section></PublicShell>;
  if (!data) return <PublicShell><PublicHeader /><section className="public-menu-state">Opening the menu…</section></PublicShell>;
  return <PublicShell><PublicHeader /><section className="public-menu-hero"><Link href={`/r/${tenantSlug}/${locationSlug}`} className="public-menu-back">← {data.location.name}</Link><p className="eyebrow">{data.restaurant.name}</p><h1>The full <em>menu.</em></h1><p>Browse what is being served at {data.location.name}. Scan your table QR when you are ready to place a dine-in order.</p></section><nav className="public-menu-filters" aria-label="Filter menu"><button aria-pressed={filter === "ALL"} onClick={() => setFilter("ALL")}>Everything</button><button aria-pressed={filter === "FOOD"} onClick={() => setFilter("FOOD")}>Food</button><button aria-pressed={filter === "DRINK"} onClick={() => setFilter("DRINK")}>Drinks</button></nav><section className="public-menu-list">{categories.map(category => <section className="menu-category" key={category.name}><div className="category-heading"><p className="eyebrow">{category.items[0]?.item_type === "DRINK" ? "From the bar" : "From the kitchen"}</p><h2>{category.name}</h2></div><div className="store-card-grid">{category.items.map((item, index) => <article className={`store-card ${item.item_type === "DRINK" ? "drink-card" : ""}`} key={`${category.name}-${item.name}`}><div className={`dish-art ${item.item_type === "DRINK" ? "is-drink" : ""}`} aria-hidden="true"><span>{["✦", "✳", "✹", "✺"][index % 4]}</span><i /><b /></div><div className="card-copy"><small>{item.item_type === "DRINK" ? "From the bar" : "From the kitchen"}</small><b>{item.name}</b><span>{item.description || "Made fresh to order."}</span><strong>{money(item.price, item.currency ?? data.location.currency)}</strong></div>{item.available === false && <em>Sold out</em>}</article>)}</div></section>)}</section></PublicShell>;
}
