import os
import random
import subprocess
import json
import sys
from datetime import datetime

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
    return int(datetime.utcnow().strftime('%j'))

def get_current_timestamp():
    return datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ')

def create_issue(title, body, token):
    cmd = ['gh', 'issue', 'create', '--repo', REPO, '--title', title, '--body', body]
    output = run_command(cmd, token)
    # Output is typically the URL, e.g., https://github.com/owner/repo/issues/123
    return int(output.split('/')[-1])

def create_pr(title, body, head_branch, token):
    cmd = ['gh', 'pr', 'create', '--repo', REPO, '--head', head_branch, '--base', DEFAULT_BRANCH, '--title', title, '--body', body]
    output = run_command(cmd, token)
    # Output is typically the URL, e.g., https://github.com/owner/repo/pull/456
    return int(output.split('/')[-1])

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

def configure_git_identity(name=None, email=None):
    if not name:
        name = os.environ.get("GIT_USER_NAME", "Daily Ops Bot")
    if not email:
        email = os.environ.get("GIT_USER_EMAIL", "daily-ops-bot@example.com")

    run_command(['git', 'config', 'user.name', name])
    run_command(['git', 'config', 'user.email', email])

def ensure_label_exists(name, color, description, token):
    # Check if label exists
    try:
        run_command(['gh', 'label', 'view', name, '--repo', REPO], token)
    except subprocess.CalledProcessError:
        # Label doesn't exist, create it
        print(f"Creating label '{name}'...")
        run_command(['gh', 'label', 'create', name, '--repo', REPO, '--color', color, '--description', description], token)

def main():
    # 1. Random Skip (1 in 7 chance)
    if random.randint(1, 7) == 1:
        print("Random skip day triggered. Exiting.")
        return

    day_of_year = get_day_of_year()
    print(f"Day of year: {day_of_year}")
    
    # Ensure labels exist
    ensure_label_exists('has-pr', '0E8A16', 'Indicates this issue has an attached PR', GITHUB_TOKEN)
    ensure_label_exists('has-issue', '1D76DB', 'Indicates this PR is attached to an issue', GITHUB_TOKEN)
    
    # Queue Processing Function
    def process_queue():
        print("Processing queue...")
        unlinked_issues = get_open_issues_without_pr()
        unlinked_prs = get_open_prs_without_issue()
        
        while unlinked_issues and unlinked_prs:
            issue = unlinked_issues.pop(0)
            pr = unlinked_prs.pop(0)
            # Use GITHUB_TOKEN for linking actions (bot permissions usually sufficient)
            link_pr_to_issue(pr['number'], issue['number'], GITHUB_TOKEN)

    if day_of_year % 2 == 0:
        print("Even day operations.")
        
        # Determine Issue Creator
        # Index = day_of_year / 2. If index is Odd -> User, Even -> Bot
        index = day_of_year // 2
        
        if index % 2 != 0:
            print(f"Index {index} is Odd. Creating issues as User (sreekaran).")
            issue_token = PERSONAL_ACCESS_TOKEN
        else:
            print(f"Index {index} is Even. Creating issues as Bot.")
            issue_token = GITHUB_TOKEN
            
        # Create Issues (1-4)
        num_issues = random.randint(1, 4)
        print(f"Creating {num_issues} issues...")
        for i in range(num_issues):
            ts = get_current_timestamp()
            create_issue(f"Random Issue {ts} #{i+1}", f"Auto-generated issue on even day {day_of_year}.", issue_token)
            
        # Create Bot PRs (1-4)
        # Configure git for Bot
        configure_git_identity("github-actions[bot]", "github-actions[bot]@users.noreply.github.com")
        
        num_prs = random.randint(1, 4)
        print(f"Creating {num_prs} Bot PRs...")
        for i in range(num_prs):
            ts = get_current_timestamp()
            branch_name = f"auto/bot-pr-{day_of_year}-{i}-{random.randint(1000,9999)}"
            create_git_branch(branch_name)
            create_pr(f"Random Bot PR {ts} #{i+1}", f"Auto-generated bot PR on even day {day_of_year}.", branch_name, GITHUB_TOKEN)
            
        # Process Queue
        process_queue()
        
    else:
        print("Odd day operations.")
        
        # Create User PRs (1-2)
        # Configure git for User
        configure_git_identity()
        
        num_prs = random.randint(1, 2)
        print(f"Creating {num_prs} User PRs...")
        for i in range(num_prs):
            ts = get_current_timestamp()
            branch_name = f"auto/user-pr-{day_of_year}-{i}-{random.randint(1000,9999)}"
            create_git_branch(branch_name)
            create_pr(f"Random User PR {ts} #{i+1}", f"Auto-generated user PR on odd day {day_of_year}.", branch_name, PERSONAL_ACCESS_TOKEN)
            
        # Process Queue (Link new PRs to existing issues if available)
        process_queue()
        
        # Merge User PRs (attached to issue)
        # Find PRs created by user (we can't easily filter by author in 'gh pr list' without parsing, 
        # but we can check the label 'has-issue' and assume we want to merge them if they are user PRs.
        # However, recipe says "merge all user PRs attached to an issue".
        # We can differentiate by branch name pattern 'user-pr' vs 'bot-pr' or fetch author.
        print("Merging User PRs...")
        cmd = ['gh', 'pr', 'list', '--repo', REPO, '--state', 'open', '--json', 'number,headRefName,labels', '--limit', '100']
        prs = json.loads(run_command(cmd, GITHUB_TOKEN))
        
        for pr in prs:
            if 'user-pr' in pr['headRefName'] and any(l['name'] == 'has-issue' for l in pr['labels']):
                print(f"Merging User PR #{pr['number']}")
                run_command(['gh', 'pr', 'merge', str(pr['number']), '--repo', REPO, '--merge', '--delete-branch'], PERSONAL_ACCESS_TOKEN)
        
        # Approve Bot PRs (attached to issue) (1-2)
        print("Approving Bot PRs...")
        bot_prs_linked = [p for p in prs if 'bot-pr' in p['headRefName'] and any(l['name'] == 'has-issue' for l in p['labels'])]
        num_to_approve = min(len(bot_prs_linked), random.randint(1, 2))
        
        for i in range(num_to_approve):
            pr = bot_prs_linked[i]
            print(f"Approving Bot PR #{pr['number']}")
            run_command(['gh', 'pr', 'review', str(pr['number']), '--repo', REPO, '--approve', '--body', 'LGTM'], PERSONAL_ACCESS_TOKEN)
            
        # Merge Bot PRs (attached + approved)
        print("Merging Approved Bot PRs...")
        # Re-fetch PRs to get updated review status, or just iterate and check
        # We need to check review status for bot PRs
        cmd = ['gh', 'pr', 'list', '--repo', REPO, '--state', 'open', '--json', 'number,headRefName,labels,reviews', '--limit', '100']
        prs_full = json.loads(run_command(cmd, GITHUB_TOKEN))
        
        for pr in prs_full:
            if 'bot-pr' in pr['headRefName'] and any(l['name'] == 'has-issue' for l in pr['labels']):
                # Check for approval
                # API returns list of reviews. Check if any is APPROVED by me (sreekaran)
                # For simplicity, we just check if *any* state is APPROVED since I am the only reviewer usually.
                # To be precise, we could check the reviewer login.
                # Assuming 'reviews' field structure or fetching individually
                # 'reviews' in list view might be empty, better to fetch individually if needed, 
                # but let's try 'reviewDecision' if available in list. 'reviewDecision' is 'APPROVED'.
                
                # Let's verify review status using reviewDecision
                status_cmd = ['gh', 'pr', 'view', str(pr['number']), '--repo', REPO, '--json', 'reviewDecision']
                decision = json.loads(run_command(status_cmd, GITHUB_TOKEN)).get('reviewDecision')
                
                if decision == 'APPROVED':
                    print(f"Merging Bot PR #{pr['number']}")
                    run_command(['gh', 'pr', 'merge', str(pr['number']), '--repo', REPO, '--merge', '--delete-branch'], PERSONAL_ACCESS_TOKEN)

        # Close Issues linked to merged PRs
        # The "Fixes #ID" in body should auto-close issues when PR is merged to default branch.
        # So explicit closing might be redundant if we used the keyword correctly.
        # But if we want to be sure:
        print("Verifying closed issues...")
        # Since we used "Fixes #ID", GitHub handles this. 
        # But if we want to explicitly close any that were missed:
        # We would need to track which PRs were just merged and parse their bodies to find the issue number.
        # Given the requirement "close all the issues that have a merged pr attached to them",
        # relying on GitHub's "Fixes" keyword is the standard "recipe" way.
        # I will assume the "Fixes" keyword handles this.

if __name__ == "__main__":
    main()
