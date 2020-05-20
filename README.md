This script generates a simple budget report for GnuCash accounts. The reports can be configured to use different accounts and will look like this:

![](sample_plot.png)

# Setup
I have only tested this on python 3.8.1, so be warned. I believe it requires python 3.x or newer, but I could be wrong.

1. Make sure that your GnuCash file is saved in SQLite format.
2. Run `pip install -r requirements.txt`. I recommend using a virtualenv or similar.

# Running
To run the command, provide it with a path to your gnucash file, the accounts you want to use, and the budgets for each account. Use `python3 budget.py --help` for more info on the desired format. Here's a sample command:

```
python budget.py ../gnucash/main.gnucash \
    --ignored_accounts="Expenses:Taxes,Expenses:401k Management,Expenses:Rent" \
    --accounts="Expenses,Expenses:Food,Expenses:Leisure" \
    --budgets="0,0,0"
```

If you are using a version of GnuCash >3.7, you may need to use the `--unsupported_table_hotfix` flag to get this to run (until piecash pushes a release that fixes that bug)