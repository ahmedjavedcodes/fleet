"use client";

import { Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

import type { FuelTrendPoint } from "@/lib/types/dashboard";

export function FuelTrendChart({ data }: { data: FuelTrendPoint[] }) {
  return (
    <ResponsiveContainer width="100%" height="100%">
      <LineChart data={data}>
        <XAxis dataKey="month" fontSize={12} />
        <YAxis fontSize={12} />
        <Tooltip formatter={(value: number) => `$${value.toFixed(2)}`} />
        <Line type="monotone" dataKey="total_cost" strokeWidth={2} dot={false} name="Fuel cost" />
      </LineChart>
    </ResponsiveContainer>
  );
}
