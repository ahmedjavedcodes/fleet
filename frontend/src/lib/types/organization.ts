// Mirrors backend/app/schemas/organization.py::OrganizationResponse
import type { SubscriptionTier } from "./enums";

export interface OrganizationResponse {
  id: string;
  name: string;
  slug: string;
  subscription_tier: SubscriptionTier;
  created_at: string;
}
