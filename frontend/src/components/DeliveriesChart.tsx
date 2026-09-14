"use client";

import { Line, LineChart, ResponsiveContainer, XAxis, YAxis } from "recharts";

export interface DeliveriesChartProps {
  data: { month: string; deliveries: number }[];
}

export function DeliveriesChart({ data }: DeliveriesChartProps) {
  return (
    <ResponsiveContainer width="100%" height="100%">
      <LineChart data={data}>
        <XAxis dataKey="month" />
        <YAxis />
        <Line type="monotone" dataKey="deliveries" strokeWidth={2} />
      </LineChart>
    </ResponsiveContainer>
  );
}
