"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { apiClient } from "../../lib/api";
import { getPublicCached } from "../../lib/public-cache";
import styles from "./public-restaurant.module.css";

export type PublicLocation = {
  slug: string;
  name: string;
  address?: string | null;
  cover_image_url?: string | null;
  is_open?: boolean;
  opening_hours?: string | null;
  currency?: string;
  menu_item_count?: number;
};

export type PublicRestaurant = {
  slug: string;
  name: string;
  description?: string | null;
  cover_image_url?: string | null;
  locations: PublicLocation[];
};

export type PublicMenuItem = {
  slug?: string;
  name: string;
  description?: string | null;
  image_url?: string | null;
  price: number | string;
  currency?: string;
  category_name?: string | null;
  available?: boolean;
};

export type PublicLocationDetail = PublicLocation & {
  restaurant: Pick<PublicRestaurant, "slug" | "name" | "description" | "cover_image_url">;
  menu?: PublicMenuItem[];
  menu_items?: PublicMenuItem[];
  maps_url?: string | null;
};

type PublicLocationApiResponse = {
  restaurant: PublicLocationDetail["restaurant"];
  location: PublicLocation;
  menu: Array<{ name: string; items: PublicMenuItem[] }>;
};

function formatMoney(value: number | string, currency = "NGN") {
  return new Intl.NumberFormat("en-NG", { style: "currency", currency, maximumFractionDigits: 0 }).format(Number(value));
}

function cover(url?: string | null) {
  return url ? { backgroundImage: `linear-gradient(135deg, rgba(20,26,23,.1), rgba(20,26,23,.7)), url(${url})` } : undefined;
}

export function PublicShell({ children }: { children: React.ReactNode }) {
  return <main className={styles.publicShell}>{children}</main>;
}

export function PublicHeader() {
  return <header className={styles.header}><Link className={styles.wordmark} href="/">CHOWLY<span>°</span></Link><nav><Link href="/restaurants">Find a restaurant</Link><Link href="/join">List your restaurant</Link><Link className={styles.staffLink} href="/login">Staff sign in</Link></nav></header>;
}

export function RestaurantDirectory() {
  const [restaurants, setRestaurants] = useState<PublicRestaurant[]>([]);
  const [query, setQuery] = useState("");
  const [status, setStatus] = useState<"loading" | "ready" | "error">("loading");
  useEffect(() => { void getPublicCached("restaurants", () => apiClient.get<PublicRestaurant[]>("/public/restaurants")).then((data) => { setRestaurants(data); setStatus("ready"); }).catch(() => setStatus("error")); }, []);
  const visible = useMemo(() => restaurants.filter((restaurant) => `${restaurant.name} ${(restaurant.locations ?? []).map((location) => `${location.name} ${location.address ?? ""}`).join(" ")}`.toLowerCase().includes(query.trim().toLowerCase())), [restaurants, query]);
  return <PublicShell><PublicHeader /><section className={styles.directoryHero}><p className={styles.kicker}>A considered table is waiting</p><h1>Find your next<br /><i>good meal.</i></h1><label className={styles.search}><span aria-hidden>⌕</span><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search a restaurant or neighbourhood" aria-label="Search restaurants" /></label></section><section className={styles.directoryGrid} aria-live="polite">{status === "loading" && <p className={styles.loading}>Finding restaurants near you…</p>}{status === "error" && <div className={styles.empty}><h2>Restaurants are taking a moment.</h2><p>Please refresh and try again.</p></div>}{status === "ready" && visible.length === 0 && <div className={styles.empty}><h2>No restaurant found.</h2><p>Try its name or a different neighbourhood.</p></div>}{visible.map((restaurant) => <Link className={styles.restaurantCard} href={`/r/${restaurant.slug}`} key={restaurant.slug}><div className={styles.cardImage} style={cover(restaurant.cover_image_url)}><span>{restaurant.locations.length} {restaurant.locations.length === 1 ? "location" : "locations"}</span></div><div><p className={styles.cardOverline}>Now on Chowly</p><h2>{restaurant.name}</h2><p>{restaurant.description || restaurant.locations.map((location) => location.name).join(" · ")}</p><b>Explore restaurant <span>→</span></b></div></Link>)}</section></PublicShell>;
}

export function RestaurantLanding({ tenantSlug }: { tenantSlug: string }) {
  const [restaurant, setRestaurant] = useState<PublicRestaurant | null>(null); const [error, setError] = useState(false);
  useEffect(() => { void getPublicCached(`restaurant:${tenantSlug}`, () => apiClient.get<PublicRestaurant>(`/public/restaurants/${encodeURIComponent(tenantSlug)}`)).then(setRestaurant).catch(() => setError(true)); }, [tenantSlug]);
  if (error) return <NotFound />;
  if (!restaurant) return <Loading />;
  return <PublicShell><PublicHeader /><section className={styles.restaurantHero} style={cover(restaurant.cover_image_url)}><div><p className={styles.kicker}>Welcome to</p><h1>{restaurant.name}</h1><p>{restaurant.description}</p></div></section><section className={styles.locationSection}><p className={styles.kicker}>Choose your spot</p><h2>Which location suits you?</h2><div className={styles.locationGrid}>{restaurant.locations.map((location) => <Link key={location.slug} href={`/r/${restaurant.slug}/${location.slug}`} className={styles.locationCard}><div className={styles.locationVisual} style={cover(location.cover_image_url ?? restaurant.cover_image_url)}><span className={location.is_open === false ? styles.closed : styles.open}>{location.is_open === false ? "Closed" : "Open now"}</span></div><h3>{location.name}</h3><p>{location.address || "Address coming soon"}</p><b>View location <span>→</span></b></Link>)}</div></section></PublicShell>;
}

export function LocationLanding({ tenantSlug, locationSlug }: { tenantSlug: string; locationSlug: string }) {
  const [location, setLocation] = useState<PublicLocationDetail | null>(null); const [error, setError] = useState(false);
  useEffect(() => { void getPublicCached(`restaurant-location:${tenantSlug}:${locationSlug}`, () => apiClient.get<PublicLocationApiResponse>(`/public/restaurants/${encodeURIComponent(tenantSlug)}/locations/${encodeURIComponent(locationSlug)}`)).then((data) => setLocation({ ...data.location, restaurant: data.restaurant, menu: data.menu.flatMap((category) => category.items.map((item) => ({ ...item, category_name: category.name }))) })).catch(() => setError(true)); }, [tenantSlug, locationSlug]);
  if (error) return <NotFound />;
  if (!location) return <Loading />;
  const menu = location.menu ?? location.menu_items ?? [];
  return <PublicShell><PublicHeader /><section className={styles.locationHero} style={cover(location.cover_image_url ?? location.restaurant.cover_image_url)}><div><Link href={`/r/${tenantSlug}`} className={styles.back}>← All locations</Link><p className={styles.kicker}>{location.restaurant.name}</p><h1>{location.name}</h1><p>{location.address}</p><div className={styles.heroMeta}><span className={location.is_open === false ? styles.closed : styles.open}>{location.is_open === false ? "Closed now" : "Open today"}</span>{location.opening_hours && <span>{location.opening_hours}</span>}</div></div></section><section className={styles.locationActions}><div><p className={styles.kicker}>Planning ahead?</p><h2>Make a reservation.</h2><p>Request your table in under a minute. No account needed.</p></div><Link className={styles.solidButton} href={`/r/${tenantSlug}/${locationSlug}/reserve`}>Reserve a table <span>→</span></Link></section><section className={styles.menuPreview}><div className={styles.menuHeading}><div><p className={styles.kicker}>A taste of the menu</p><h2>Made for the table.</h2></div><p>{menu.length ? "Browse the full menu before you visit." : "The menu is being prepared."}</p></div><div className={styles.previewGrid}>{menu.slice(0, 6).map((item, index) => <article className={styles.menuPreviewCard} key={`${item.name}-${index}`}><div className={styles.itemImage} style={cover(item.image_url)}>{item.available === false && <span>Sold out</span>}</div><div><p>{item.category_name || "From the kitchen"}</p><h3>{item.name}</h3><small>{item.description}</small><b>{formatMoney(item.price, item.currency ?? location.currency)}</b></div></article>)}</div>{menu.length > 0 && <Link className={styles.solidButton} href={`/r/${tenantSlug}/${locationSlug}/menu`}>View full menu <span>→</span></Link>}{location.maps_url && <a className={styles.mapLink} href={location.maps_url} target="_blank" rel="noreferrer">Get directions <span>↗</span></a>}</section></PublicShell>;
}

function Loading() { return <PublicShell><PublicHeader /><div className={styles.pageState}>Loading this restaurant…</div></PublicShell>; }
function NotFound() { return <PublicShell><PublicHeader /><div className={styles.pageState}><p className={styles.kicker}>Not available</p><h1>This page is private<br />or no longer live.</h1><Link className={styles.solidButton} href="/restaurants">Find a restaurant</Link></div></PublicShell>; }
