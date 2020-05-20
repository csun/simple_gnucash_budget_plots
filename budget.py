import argparse
import calendar
import datetime
import heapq
import os
import os.path
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import piecash
import re

from piecash import open_book
from piecash.core import Transaction


class CumulativeTree(object):
    
    def __init__(self, name, buckets_count):
        self.name = name
        self.buckets = np.zeros(buckets_count)
        self.latest_bucket = 0
        self.children = {}
        self.sorted_children = None
    
    def ingest_split(self, path, bucket, split):
        assert path[0] == self.name
        assert bucket >= self.latest_bucket, 'Must ingest splits in date order'

        if len(path) == 1:
            # base case - add the value of transaction to this node
            if bucket != self.latest_bucket:
                for i in range(self.latest_bucket + 1, bucket + 1):
                    self.buckets[i] = self.buckets[self.latest_bucket]
                self.latest_bucket = bucket

            self.buckets[bucket] += float(split.value)
        else:
            # recursive case
            if path[1] not in self.children:
                self.children[path[1]] = CumulativeTree(path[1], self.buckets.size)
            self.children[path[1]].ingest_split(path[1:], bucket, split)
    
    def finalize(self, name_prefix=None):
        if name_prefix is None:
            name_prefix = self.name
        else:
            name_prefix = name_prefix + ':' + self.name

        for i in range(self.latest_bucket + 1, self.buckets.size):
            self.buckets[i] = self.buckets[self.latest_bucket]
        
        self.sorted_children = []
        for _, child in self.children.items():
            if (name_prefix + ':' + child.name) in global_ignored_accounts:
                continue

            child.finalize(name_prefix=name_prefix)
            self.sorted_children.append(child)
            self.buckets = np.add(self.buckets, child.buckets)
        
        self.sorted_children.sort(key=lambda child : -child.buckets[-1])
        
    
    def to_dataframe(self, depth=1, name_prefix=None, index=None):
        assert self.sorted_children is not None, 'Please run finalize() first'
        dataframe = pd.DataFrame(index=index)

        if name_prefix is None:
            name_prefix = self.name
        else:
            name_prefix += ':' + self.name

        # Actual work of converting to dataframe
        dataframe.insert(0, name_prefix, self.buckets)
        if depth > 0:
            for child in self.sorted_children:
                child_dataframe = child.to_dataframe(depth - 1, name_prefix=name_prefix, index=index)
                dataframe = dataframe.join(child_dataframe)

        return dataframe
    
    def get_node(self, path):
        assert self.name == path[0]
        
        if len(path) == 1:
            return self
        elif path[1] in self.children:
            return self.children[path[1]].get_node(path[1:])
        else:
            return None


class CumulativeAccountsIngester(object):

    def __init__(self, book, start_date, end_date):
        self.book = book
        self.start_date = start_date
        self.end_date = end_date
        self.total_buckets = (self.end_date - self.start_date).days + 1
        self.trees = {}
        self.has_started = False

    def start(self):
        self.has_started = True
        transactions = (self.book.session.query(Transaction).filter(Transaction.post_date>=self.start_date)
            .filter(Transaction.post_date<=self.end_date)
            .order_by(Transaction.post_date).all())

        for transaction in transactions:
            bucket = (transaction.post_date - self.start_date).days
            for split in transaction.splits:
                path = split.account.fullname.split(':')
                base_acc = path[0]

                if base_acc not in self.trees:
                    self.trees[base_acc] = CumulativeTree(base_acc, self.total_buckets)
                
                self.trees[base_acc].ingest_split(path, bucket, split)

        for _, tree in self.trees.items():
            tree.finalize()

    def get_dataframe_for_account(self, account, depth=1):
        path = account.split(':')

        if path[0] not in self.trees:
            return None

        index = pd.date_range(start=self.start_date, periods=self.total_buckets, freq='D')
        node = self.trees[path[0]].get_node(path)
        if node is None:
            return None

        return node.to_dataframe(depth, index=index)


def last_day_of_month(any_day):
    next_month = any_day.replace(day=28) + datetime.timedelta(days=4)
    return next_month - datetime.timedelta(days=next_month.day)


def plot_dataframe(dataframe, title, filename, budget=None):
    if dataframe is None:
        return

    plt.style.use('fivethirtyeight')

    total_rows = len(dataframe.index)
    budget_col = np.zeros(total_rows)
    budget /= total_rows
    for i in range(total_rows):
        budget_col[i] = budget * (i + 1)
    dataframe.insert(0, 'BUDGET', budget_col)

    fig = dataframe.plot(title=title, linewidth=2).figure
    fig.set_size_inches(19.2, 10.8)
    fig.savefig(filename, dpi=300)


def plot_ingester(ingester, accounts, budgets, title_prefix='', filename_prefix='', monthly_budget_multiplier=1.0):
    def plot_ingester_single(account, filename_suffix, monthly_budget):
        output = filename_prefix + filename_suffix
        print('== Plotting {}'.format(output))
        
        try:
            modified_date = datetime.datetime.fromtimestamp(os.path.getmtime(output)).date()
            file_needs_update = modified_date < ingester.end_date
        except OSError:
            file_needs_update = True

        if not file_needs_update:
            print('\tPlot has been updated since end date of range. Skipping.')
            return

        if not ingester.has_started:
            ingester.start()

        plot_dataframe(ingester.get_dataframe_for_account(account), title_prefix + account,
            output, budget=monthly_budget_multiplier * monthly_budget)

    for i in range(len(accounts)):
        plot_ingester_single(
            accounts[i],
            re.sub(r':| ', '_', accounts[i].lower()) + '.svg',
            budgets[i])


def main():
    this_folder = os.path.dirname(os.path.realpath(__file__))

    parser = argparse.ArgumentParser(description='Generate monthly and yearly budget plots for GnuCash accounts')
    parser.add_argument('gnucash_file', help='Path to a gnucash file stored in SQLite format')
    parser.add_argument('--output_folder', '-o',default=this_folder, help='Path to reports output folder')
    parser.add_argument('--accounts', type=str, default='Expenses',
        help='Comma-separated list of account names to plot')
    parser.add_argument('--budgets', type=str, default='0',
        help=('Comma-separated list of monthly budgets. Each element should be the '
              'budget for the account with the corresponding index'))
    parser.add_argument('--ignored_accounts', type=str, default='Expenses',
        help='Comma-separated list of account names to ignore')
    # TODO remove this flag when piecash fixes the bug
    parser.add_argument('--unsupported_table_hotfix', action='store_true',
        help='Hotfix for unsupported table versions error')
    args = parser.parse_args()

    global global_ignored_accounts
    global_ignored_accounts = set(args.ignored_accounts.split(','))
    args.accounts = args.accounts.split(',')
    args.budgets = list(map(float, args.budgets.split(',')))

    if args.unsupported_table_hotfix:
        piecash.core.session.version_supported['3.0']['Gnucash'] = 3000001
        piecash.core.session.version_supported['3.0']['splits'] = 5

    book = open_book(args.gnucash_file, open_if_lock=True)

    # TODO make dates more configurable
    for year in range(2020, datetime.date.today().year + 1):
        reports_folder = os.path.join(args.output_folder, str(year))
        os.makedirs(reports_folder, exist_ok=True)

        ytd_start_date = datetime.date(year, 1, 1)
        ytd_end_date = datetime.date.today()
        cur_year_end = datetime.date(year, 12, 31)
        if cur_year_end < ytd_end_date:
            ytd_end_date = cur_year_end

        cur_month = ytd_end_date.month
        cur_month_days = calendar.monthrange(year, cur_month)[1]
        ytd_budget_multiplier = cur_month - ((cur_month_days - ytd_end_date.day) / cur_month_days)

        ingester = CumulativeAccountsIngester(book, ytd_start_date, ytd_end_date)
        plot_ingester(ingester,
            args.accounts,
            args.budgets,
            title_prefix='YTD ',
            filename_prefix=os.path.join(reports_folder, 'ytd_'),
            monthly_budget_multiplier=ytd_budget_multiplier)

        for month in range(1, ytd_end_date.month + 1):
            month_start_date = datetime.date(year, month, 1)
            month_end_date = last_day_of_month(month_start_date)

            ingester = CumulativeAccountsIngester(book, month_start_date, month_end_date)
            plot_ingester(ingester,
                args.accounts,
                args.budgets,
                title_prefix='{} '.format(month_start_date.strftime('%B')),
                filename_prefix=os.path.join(reports_folder, 'month_{}_'.format(month)))


if __name__=='__main__':
    main()
