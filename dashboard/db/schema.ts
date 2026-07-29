import { sql } from "drizzle-orm";
import { sqliteTable, text } from "drizzle-orm/sqlite-core";

export const deviceClaims = sqliteTable("device_claims", {
  inviteHash: text("invite_hash").primaryKey(),
  deviceHash: text("device_hash").notNull().unique(),
  claimedAt: text("claimed_at").notNull().default(sql`CURRENT_TIMESTAMP`),
});
