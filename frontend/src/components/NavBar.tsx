"use client";

import { AlertTriangle, Bot, Fuel, LayoutDashboard, LogOut, Truck, Wrench } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";

import { useAuth } from "@/lib/auth-context";

const LINKS = [
  { href: "/dashboard", label: "Dashboard", icon: LayoutDashboard },
  { href: "/registry", label: "Registry", icon: Truck },
  { href: "/fuel", label: "Fuel", icon: Fuel },
  { href: "/maintenance", label: "Maintenance", icon: Wrench },
  { href: "/incidents", label: "Incidents", icon: AlertTriangle },
  { href: "/copilot", label: "Copilot", icon: Bot },
] as const;

export function NavBar() {
  const pathname = usePathname();
  const { session, logout } = useAuth();

  if (!session) return null;

  return (
    <nav className="flex h-14 items-center justify-between border-b border-neutral-200 px-6 dark:border-neutral-800">
      <div className="flex items-center gap-6">
        <span className="text-sm font-semibold">{session.organization.name}</span>
        <div className="flex items-center gap-1">
          {LINKS.map(({ href, label, icon: Icon }) => {
            const active = pathname.startsWith(href);
            return (
              <Link
                key={href}
                href={href}
                className={`flex items-center gap-1.5 rounded-md px-3 py-1.5 text-sm ${
                  active
                    ? "bg-neutral-900 text-white dark:bg-white dark:text-neutral-900"
                    : "text-neutral-600 hover:bg-neutral-100 dark:text-neutral-400 dark:hover:bg-neutral-900"
                }`}
              >
                <Icon className="h-4 w-4" />
                {label}
              </Link>
            );
          })}
        </div>
      </div>
      <button
        onClick={logout}
        className="flex items-center gap-1.5 text-sm text-neutral-600 hover:text-neutral-900 dark:text-neutral-400 dark:hover:text-white"
      >
        <LogOut className="h-4 w-4" />
        Sign out
      </button>
    </nav>
  );
}
