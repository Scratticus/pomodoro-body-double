import type { Plugin } from "@opencode-ai/plugin";
import * as fs from "fs";

const QUEUE_FILE = `${process.env.HOME}/.opencode/productivity/prompt_queue.json`;

interface PromptEntry {
  id: number;
  timestamp: string;
  type: string;
  prompt: string;
  delivered: boolean;
}

/**
 * Reads undelivered prompts from the queue file and marks them as delivered.
 * Returns formatted prompt messages or null if none found.
 */
function consumePrompts(): string | null {
  try {
    if (!fs.existsSync(QUEUE_FILE)) {
      return null;
    }

    const content = fs.readFileSync(QUEUE_FILE, "utf-8");
    const queue: PromptEntry[] = JSON.parse(content);

    const undelivered = queue.filter((e) => !e.delivered);
    if (undelivered.length === 0) {
      return null;
    }

    // Mark as delivered
    for (const entry of undelivered) {
      entry.delivered = true;
    }

    // Atomic write
    const tmpFile = `${QUEUE_FILE}.tmp`;
    fs.writeFileSync(tmpFile, JSON.stringify(queue, null, 2));
    fs.renameSync(tmpFile, QUEUE_FILE);

    // Format messages
    const msgs = undelivered.map((e) => `[${e.type}] ${e.prompt}`);
    return msgs.join(" | ");
  } catch (error) {
    // Silently fail - don't break the workflow
    return null;
  }
}

/**
 * OpenCode plugin for Pomodoro Body Double system.
 * Hooks into prompt submission and tool use events to inject pomodoro reminders.
 */
const PomodoroPlugin: Plugin = async (ctx) => {
  return {
    // Hook into when user submits a prompt
    "prompt.submitted": async (input, output) => {
      const prompts = consumePrompts();
      if (prompts) {
        output.context.push(`
## Pomodoro Transition

The following pomodoro prompts are queued and should be handled:

${prompts}

Please acknowledge these transitions and ask the user what they'd like to do next.
`);
      }
    },

    // Hook into after tool use completes
    "tool.used": async (input, output) => {
      const prompts = consumePrompts();
      if (prompts) {
        output.context.push(`
## Pomodoro Transition

The following pomodoro prompts are queued and should be handled:

${prompts}

Please acknowledge these transitions and ask the user what they'd like to do next.
`);
      }
    },

    // Session start hook
    "session.started": async (input, output) => {
      // Clear any stale queue at session start
      try {
        if (fs.existsSync(QUEUE_FILE)) {
          fs.writeFileSync(QUEUE_FILE, "[]");
        }
      } catch (error) {
        // Ignore errors
      }

      output.context.push(`
## Session Start

This is a Pomodoro Body Double session. You act as an accountability partner managing work/break cycles.

**On startup you must:**
1. Request read/write for ~/.opencode/productivity/ directory
2. Initialize prompt_queue.json: echo '[]' > ~/.opencode/productivity/prompt_queue.json
3. Read session.yaml and tasks.yaml
4. Check water/hydration status
5. Ask about any chores to start (laundry, dishwasher, etc.)
6. Show task list and ask what to work on
7. Run 'date' to check current time
8. Ask what time to wrap up (default 5:30 PM)

**Once user picks a task, write startup ack:**
echo "continue:Task Name" > ~/.opencode/productivity/acknowledged.txt
`);
    },
  };
};

export default PomodoroPlugin;
