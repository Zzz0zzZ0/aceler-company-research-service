#!/usr/bin/env node
"use strict";

// Preserve the key supplied by the research service before the AnySearch CLI
// loads its own .env file, then pass it through the CLI's highest-priority
// option. The key is added inside Node so it is not exposed in the OS command
// line shown by process-listing tools.
const configuredKey = process.env.ANYSEARCH_API_KEY || "";
if (configuredKey) process.argv.push("--api_key", configuredKey);
require(process.env.ANYSEARCH_CLI_PATH);
