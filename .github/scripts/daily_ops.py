import os
import random
import subprocess
import json
import sys
import argparse
from datetime import datetime, timezone

# Environment variables
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN")
PERSONAL_ACCESS_TOKEN = os.environ.get("PERSONAL_ACCESS_TOKEN")
REPO = os.environ.get("GITHUB_REPOSITORY")
DEFAULT_BRANCH = os.environ.get("DEFAULT_BRANCH", "main")
RUN_ID = os.environ.get("GITHUB_RUN_ID", "local")

if not GITHUB_TOKEN or not PERSONAL_ACCESS_TOKEN or not REPO:
    print("Error: GITHUB_TOKEN, PERSONAL_ACCESS_TOKEN, and GITHUB_REPOSITORY must be set.")
    sys.exit(1)

def run_command(command, token=None):
    """Runs a shell command and returns the output."""
    env = os.environ.copy()
    if token:
        env["GH_TOKEN"] = token
    
    try:
        # Use shell=False and pass command as list for security
        result = subprocess.run(
            command,
            shell=False,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=env
        )
        return result.stdout.strip()
    except subprocess.CalledProcessError as e:
        print(f"Error running command: {command}")
        print(f"Stdout: {e.stdout}")
        print(f"Stderr: {e.stderr}")
        raise

def get_day_of_year():
    return int(datetime.now(timezone.utc).strftime('%j'))

def get_current_timestamp():
    return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')

def create_issue(title, body, token):
    # gh issue create returns the URL of the created issue
    cmd = ['gh', 'issue', 'create', '--repo', REPO, '--title', title, '--body', body]
    output = run_command(cmd, token)
    # Output is typically the URL, e.g., https://github.com/owner/repo/issues/123
    return int(output.strip().split('/')[-1])

def create_pr(title, body, head_branch, token):
    # gh pr create returns the URL of the created PR
    cmd = ['gh', 'pr', 'create', '--repo', REPO, '--head', head_branch, '--base', DEFAULT_BRANCH, '--title', title, '--body', body]
    output = run_command(cmd, token)
    # Output is typically the URL, e.g., https://github.com/owner/repo/pull/456
    return int(output.strip().split('/')[-1])

def get_open_issues_without_pr():
    cmd = ['gh', 'issue', 'list', '--repo', REPO, '--state', 'open', '--json', 'number,labels,title', '--limit', '100']
    output = run_command(cmd, GITHUB_TOKEN) # Token doesn't matter much for reading public/repo info
    issues = json.loads(output)
    # Filter out issues that already have 'has-pr' label
    return sorted([i for i in issues if not any(l['name'] == 'has-pr' for l in i['labels'])], key=lambda x: x['number'])

def get_open_prs_without_issue():
    cmd = ['gh', 'pr', 'list', '--repo', REPO, '--state', 'open', '--json', 'number,labels,title', '--limit', '100']
    output = run_command(cmd, GITHUB_TOKEN)
    prs = json.loads(output)
    # Filter out PRs that already have 'has-issue' label
    return sorted([p for p in prs if not any(l['name'] == 'has-issue' for l in p['labels'])], key=lambda x: x['number'])

def link_pr_to_issue(pr_number, issue_number, token):
    print(f"Linking PR #{pr_number} to Issue #{issue_number}")
    
    # 1. Update Issue: Add label 'has-pr', add comment
    run_command(['gh', 'issue', 'edit', str(issue_number), '--repo', REPO, '--add-label', 'has-pr'], token)
    run_command(['gh', 'issue', 'comment', str(issue_number), '--repo', REPO, '--body', f'Linked to PR #{pr_number}'], token)
    
    # 2. Update PR: Add label 'has-issue', add comment, update body
    run_command(['gh', 'pr', 'edit', str(pr_number), '--repo', REPO, '--add-label', 'has-issue'], token)
    # Append "Fixes #IssueID" to the PR body for cross-referencing
    # First get current body
    current_body_json = run_command(['gh', 'pr', 'view', str(pr_number), '--repo', REPO, '--json', 'body'], token)
    current_body = json.loads(current_body_json).get('body')
    if current_body is None:
        current_body = ""
    new_body = f"{current_body}\n\nFixes #{issue_number}".strip()
    run_command(['gh', 'pr', 'edit', str(pr_number), '--repo', REPO, '--body', new_body], token)
    run_command(['gh', 'pr', 'comment', str(pr_number), '--repo', REPO, '--body', f'Linked to Issue #{issue_number}'], token)

def create_git_branch(branch_name):
    # Determine the token to use for git operations based on identity
    # For simplicity, we assume the environment is set up correctly by the workflow 
    # or we use the GITHUB_TOKEN for basic git ops if needed.
    # However, to push as a specific user, the workflow needs to configure git config.
    
    run_command(['git', 'fetch', 'origin', DEFAULT_BRANCH])
    run_command(['git', 'checkout', DEFAULT_BRANCH])
    run_command(['git', 'checkout', '-b', branch_name])
    run_command(['git', 'commit', '--allow-empty', '-m', f'Empty commit for {branch_name}'])
    run_command(['git', 'push', 'origin', branch_name])

def configure_git_identity(name, email):
    run_command(['git', 'config', 'user.name', name])
    run_command(['git', 'config', 'user.email', email])

def ensure_label_exists(name, color, description, token):
    print(f"Ensuring label '{name}' exists...")
    try:
        # Use 'list' instead of 'view' as 'view' is not supported in all gh versions
        cmd = ['gh', 'label', 'list', '--repo', REPO, '--json', 'name']
        output = run_command(cmd, token)
        labels = json.loads(output)
        existing_names = [l['name'] for l in labels]
        
        if name in existing_names:
            print(f"Label '{name}' already exists.")
            return

        print(f"Creating label '{name}'...")
        run_command(['gh', 'label', 'create', name, '--repo', REPO, '--color', color, '--description', description], token)
        
    except Exception as e:
        print(f"Warning: Could not ensure label '{name}' exists: {e}")

# --- Atomic Operations ---

def action_create_issues(count, as_user=False):
    token = PERSONAL_ACCESS_TOKEN if as_user else GITHUB_TOKEN
    creator = "User" if as_user else "Bot"
    if not as_user:
        configure_git_identity("github-actions[bot]", "github-actions[bot]@users.noreply.github.com")
    
    print(f"Creating {count} issues as {creator}...")
    for i in range(count):
        ts = get_current_timestamp()
        create_issue(f"Random Issue {ts} #{i+1}", f"Auto-generated issue by {creator}.", token)

def action_create_prs(count, as_user=False):
    token = PERSONAL_ACCESS_TOKEN if as_user else GITHUB_TOKEN
    creator = "User" if as_user else "Bot"
    prefix = "user" if as_user else "bot"
    
    if as_user:
        configure_git_identity("sreekaran", "ss@sreekaran.com")
    else:
        configure_git_identity("github-actions[bot]", "github-actions[bot]@users.noreply.github.com")

    print(f"Creating {count} PRs as {creator}...")
    for i in range(count):
        ts = get_current_timestamp()
        branch_name = f"auto/{prefix}-pr-{get_day_of_year()}-{i}-{random.randint(1000,9999)}"
        create_git_branch(branch_name)
        create_pr(f"Random {creator} PR {ts} #{i+1}", f"Auto-generated {prefix} PR.", branch_name, token)

def action_link_prs_issues(count=100):
    print(f"Processing queue (Linking up to {count} PRs to Issues)...")
    unlinked_issues = get_open_issues_without_pr()
    unlinked_prs = get_open_prs_without_issue()
    
    # Process as many pairs as possible
    processed = 0
    while unlinked_issues and unlinked_prs and processed < count:
        issue = unlinked_issues.pop(0)
        pr = unlinked_prs.pop(0)
        # Use GITHUB_TOKEN for linking actions (bot permissions usually sufficient)
        link_pr_to_issue(pr['number'], issue['number'], GITHUB_TOKEN)
        processed += 1

def action_merge_prs(as_user_prs=False, count=100, merge_token=PERSONAL_ACCESS_TOKEN):
    target_type = "User" if as_user_prs else "Bot"
    search_str = 'user-pr' if as_user_prs else 'bot-pr'
    
    print(f"Merging up to {count} {target_type} PRs...")
    cmd = ['gh', 'pr', 'list', '--repo', REPO, '--state', 'open', '--json', 'number,headRefName,labels,reviews', '--limit', '100']
    prs = json.loads(run_command(cmd, GITHUB_TOKEN))
    
    processed = 0
    for pr in prs:
        if processed >= count:
            break

        if search_str in pr['headRefName'] and any(l['name'] == 'has-issue' for l in pr['labels']):
            
            # For Bot PRs, we usually require approval first
            if not as_user_prs:
                # Check review decision
                status_cmd = ['gh', 'pr', 'view', str(pr['number']), '--repo', REPO, '--json', 'reviewDecision']
                decision = json.loads(run_command(status_cmd, GITHUB_TOKEN)).get('reviewDecision')
                
                if decision != 'APPROVED':
                    print(f"Skipping Bot PR #{pr['number']} (Not APPROVED)")
                    continue

            print(f"Merging {target_type} PR #{pr['number']}")
            run_command(['gh', 'pr', 'merge', str(pr['number']), '--repo', REPO, '--merge', '--delete-branch'], merge_token)
            processed += 1

def action_approve_bot_prs(count):
    print(f"Approving up to {count} Bot PRs...")
    cmd = ['gh', 'pr', 'list', '--repo', REPO, '--state', 'open', '--json', 'number,headRefName,labels', '--limit', '100']
    prs = json.loads(run_command(cmd, GITHUB_TOKEN))
    
    bot_prs_linked = [p for p in prs if 'bot-pr' in p['headRefName'] and any(l['name'] == 'has-issue' for l in p['labels'])]
    num_to_approve = min(len(bot_prs_linked), count)
    
    for i in range(num_to_approve):
        pr = bot_prs_linked[i]
        print(f"Approving Bot PR #{pr['number']}")
        # Use PERSONAL_ACCESS_TOKEN to approve on behalf of the user
        run_command(['gh', 'pr', 'review', str(pr['number']), '--repo', REPO, '--approve', '--body', 'LGTM'], PERSONAL_ACCESS_TOKEN)

def action_close_issues(count=100):
    # In this workflow, issues are auto-closed by "Fixes #" when PR merges.
    # But if we wanted to enforce explicit closing or clean up stuck ones:
    print(f"Verifying/Closing up to {count} issues... (Logic currently relies on 'Fixes #' keyword in PRs)")
    pass

# --- Main Logic ---

def run_daily_recipe():
    # 1. Random Skip (1 in 7 chance)
    if random.randint(1, 7) == 1:
        print("Random skip day triggered. Exiting.")
        return

    day_of_year = get_day_of_year()
    print(f"Day of year: {day_of_year}")
    
    # Ensure labels exist
    ensure_label_exists('has-pr', '0E8A16', 'Indicates this issue has an attached PR', GITHUB_TOKEN)
    ensure_label_exists('has-issue', '1D76DB', 'Indicates this PR is attached to an issue', GITHUB_TOKEN)
    
    if day_of_year % 2 == 0:
        print("Even day operations.")
        # Even Day: Issues & Bot PRs
        # Determine Issue Creator
        index = day_of_year // 2
        is_user_creator = (index % 2 != 0)
        
        count_issues = random.randint(1, 4)
        action_create_issues(count_issues, as_user=is_user_creator)
        
        count_prs = random.randint(1, 4)
        action_create_prs(count_prs, as_user=False) # Bot PRs
        
        action_link_prs_issues()
        
    else:
        print("Odd day operations.")
        # Odd Day: User PRs
        count_prs = random.randint(1, 2)
        action_create_prs(count_prs, as_user=True) # User PRs
        
        action_link_prs_issues()
    
    # Common Daily Operations
    # Merge User PRs - Use PERSONAL_ACCESS_TOKEN to simulate user merge, OR GITHUB_TOKEN if bot should do it.
    # Recipe says "merge all user PRs". Defaulting to GITHUB_TOKEN for reliability in automation.
    action_merge_prs(as_user_prs=True, merge_token=GITHUB_TOKEN) 
    
    if day_of_year % 2 != 0:
        # Odd day specific: Approve Bot PRs
        action_approve_bot_prs(random.randint(1, 2))
        
    # Merge Bot PRs (if approved)
    action_merge_prs(as_user_prs=False, merge_token=GITHUB_TOKEN)
    action_close_issues()

def main():
    parser = argparse.ArgumentParser(description="Daily Operations Script")
    parser.add_argument("--action", type=str, default="daily", 
                        choices=["daily", "create_bot_issues", "create_user_issues", 
                                 "create_bot_prs", "create_user_prs", "link_prs_issues", 
                                 "approve_bot_prs", "merge_bot_prs", "merge_user_prs", "close_issues"],
                        help="Action to perform")
    parser.add_argument("--count", type=int, default=1, help="Number of items to process (where applicable)")
    
    args = parser.parse_args()
    
    # Ensure labels exist for any operation that might need them
    ensure_label_exists('has-pr', '0E8A16', 'Indicates this issue has an attached PR', GITHUB_TOKEN)
    ensure_label_exists('has-issue', '1D76DB', 'Indicates this PR is attached to an issue', GITHUB_TOKEN)

    if args.action == "daily":
        run_daily_recipe()
    elif args.action == "create_bot_issues":
        action_create_issues(args.count, as_user=False)
    elif args.action == "create_user_issues":
        action_create_issues(args.count, as_user=True)
    elif args.action == "create_bot_prs":
        action_create_prs(args.count, as_user=False)
    elif args.action == "create_user_prs":
        action_create_prs(args.count, as_user=True)
    elif args.action == "link_prs_issues":
        action_link_prs_issues(args.count)
    elif args.action == "approve_bot_prs":
        action_approve_bot_prs(args.count)
    elif args.action == "merge_bot_prs":
        # Explicitly use GITHUB_TOKEN for bot identity merges as requested
        action_merge_prs(as_user_prs=False, count=args.count, merge_token=GITHUB_TOKEN)
    elif args.action == "merge_user_prs":
        # Explicitly use GITHUB_TOKEN for bot identity merges as requested
        action_merge_prs(as_user_prs=True, count=args.count, merge_token=GITHUB_TOKEN)
    elif args.action == "close_issues":
        action_close_issues(args.count)

if __name__ == "__main__":
    main()