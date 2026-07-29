CREATE TABLE `device_claims` (
	`invite_hash` text PRIMARY KEY NOT NULL,
	`device_hash` text NOT NULL,
	`claimed_at` text DEFAULT CURRENT_TIMESTAMP NOT NULL
);
--> statement-breakpoint
CREATE UNIQUE INDEX `device_claims_device_hash_unique` ON `device_claims` (`device_hash`);