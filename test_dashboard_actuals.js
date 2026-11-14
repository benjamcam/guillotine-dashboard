#!/usr/bin/env node
"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const html = fs.readFileSync(path.join(__dirname, "dashboard.html"), "utf8");
const match = html.match(/function actualPointsFor\(team\)\s*\{[\s\S]*?\n    \}/);
assert.ok(match, "dashboard must define actualPointsFor(team)");
const actualPointsFor = vm.runInNewContext("(" + match[0] + ")");

const fixture = {
  actual_points: 0,
  lineup: [
    {name:"Scored player A", actual_points:18.4, has_played:true},
    {name:"Scored player B", actual_points:"7.2", has_played:true},
    {name:"Not played", actual_points:null, has_played:false}
  ]
};
assert.ok(Math.abs(actualPointsFor(fixture) - 25.6) < 1e-9);
assert.equal(actualPointsFor({...fixture, actual_points:26.1}), 26.1);
assert.equal(actualPointsFor({actual_points:0, lineup:[{actual_points:0}]}), 0);
console.log("Dashboard actual-so-far checks passed (stale 0 becomes 25.6 pts).");
