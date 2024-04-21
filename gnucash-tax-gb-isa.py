#!/usr/bin/env python3
# Copyright 2024  Simon Arlott
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

from collections import defaultdict, deque, namedtuple
from datetime import datetime, timedelta
from decimal import Decimal
from fractions import Fraction
from tabulate import tabulate
import argparse
import gnucash
import locale
import logging
import re
import sys
import time


Deposit = namedtuple("Deposit", ["year", "date", "account", "amount", "type"])
Allowance = namedtuple("Allowance", ["cash", "stocks", "total"])

locale.setlocale(locale.LC_ALL, "")

ACCOUNT_DESC_ISA_RE = re.compile(r"(Closed )?(Cash|Stocks & Shares) ISA ?")
ACCOUNT_DESC_CASH_ISA_RE = re.compile(r"(Closed )?Cash ISA ?")
ACCOUNT_DESC_STOCKS_ISA_RE = re.compile(r"(Closed )?Stocks & Shares ISA ?")

ALLOWANCES = {
	"1999/00": Allowance(Decimal( "3000.00"), Decimal( "7000.00"), Decimal( "7000.00")),
	"2000/01": Allowance(Decimal( "3000.00"), Decimal( "7000.00"), Decimal( "7000.00")),
	"2001/02": Allowance(Decimal( "3000.00"), Decimal( "7000.00"), Decimal( "7000.00")),
	"2002/03": Allowance(Decimal( "3000.00"), Decimal( "7000.00"), Decimal( "7000.00")),
	"2003/04": Allowance(Decimal( "3000.00"), Decimal( "7000.00"), Decimal( "7000.00")),
	"2004/05": Allowance(Decimal( "3000.00"), Decimal( "7000.00"), Decimal( "7000.00")),
	"2005/06": Allowance(Decimal( "3000.00"), Decimal( "7000.00"), Decimal( "7000.00")),
	"2006/07": Allowance(Decimal( "3000.00"), Decimal( "7000.00"), Decimal( "7000.00")),
	"2007/08": Allowance(Decimal( "3000.00"), Decimal( "7000.00"), Decimal( "7000.00")),
	"2008/09": Allowance(Decimal( "3600.00"), Decimal( "7200.00"), Decimal( "7200.00")),
	"2009/10": Allowance(Decimal( "3600.00"), Decimal( "7200.00"), Decimal( "7200.00")),
	"2010/11": Allowance(Decimal( "5100.00"), Decimal("10200.00"), Decimal("10200.00")),
	"2011/12": Allowance(Decimal( "5340.00"), Decimal("10680.00"), Decimal("10680.00")),
	"2012/13": Allowance(Decimal( "5640.00"), Decimal("11280.00"), Decimal("11280.00")),
	"2013/14": Allowance(Decimal( "5760.00"), Decimal("11520.00"), Decimal("11520.00")),
	"2014/15": Allowance(Decimal("15000.00"), Decimal("15000.00"), Decimal("15000.00")),
	"2015/16": Allowance(Decimal("15240.00"), Decimal("15240.00"), Decimal("15240.00")),
	"2016/17": Allowance(Decimal("15240.00"), Decimal("15240.00"), Decimal("15240.00")),
	"2017/18": Allowance(Decimal("20000.00"), Decimal("20000.00"), Decimal("20000.00")),
	"2018/19": Allowance(Decimal("20000.00"), Decimal("20000.00"), Decimal("20000.00")),
	"2019/20": Allowance(Decimal("20000.00"), Decimal("20000.00"), Decimal("20000.00")),
	"2020/21": Allowance(Decimal("20000.00"), Decimal("20000.00"), Decimal("20000.00")),
	"2021/22": Allowance(Decimal("20000.00"), Decimal("20000.00"), Decimal("20000.00")),
	"2022/23": Allowance(Decimal("20000.00"), Decimal("20000.00"), Decimal("20000.00")),
	"2023/24": Allowance(Decimal("20000.00"), Decimal("20000.00"), Decimal("20000.00")),
	"2024/25": Allowance(Decimal("20000.00"), Decimal("20000.00"), Decimal("20000.00")),
}


def path2str(path):
	return ":".join(path)


def frac2gbp(frac):
	return float(frac)


def tax_year(date):
	if date.month == 4 and date.day >= 6:
		year = date.year
	elif date.month > 4:
		year = date.year
	else:
		year = date.year - 1

	return f"{year:04d}/{(year + 1) % 100:02d}"


def walk_accounts(top_account):
	accounts = deque([([], top_account)])
	while accounts:
		(path, account) = accounts.popleft()
		yield (path, account)
		accounts.extend([(path + [account.GetName()], account) for account in account.get_children_sorted()])


def is_isa_account(account):
	cty = account.GetCommodity()
	if cty and cty.get_mnemonic() == "GBP":
		return ACCOUNT_DESC_ISA_RE.match(account.GetDescription()) is not None
	return False


def isa_account_type(account):
	if ACCOUNT_DESC_CASH_ISA_RE.match(account.GetDescription()):
		return "cash"
	elif ACCOUNT_DESC_STOCKS_ISA_RE.match(account.GetDescription()):
		return "stocks"
	return None


def is_contribution_account(account):
	if is_isa_account(account):
		return False

	if account.GetType() in (gnucash.ACCT_TYPE_STOCK, gnucash.ACCT_TYPE_MUTUAL):
		return False

	if account.GetType() == gnucash.ACCT_TYPE_INCOME:
		names = set((account.GetName(),))

		parent = account.get_parent()
		while parent:
			names.add(parent.GetName())
			parent = parent.get_parent()

		if names & set(("Interest", "Dividends", "Investments")):
			return False

	return True


def isa_accounts(session):
	accounts = {}
	root_account = session.book.get_root_account()

	for (path, account) in walk_accounts(root_account):
		if is_isa_account(account):
			accounts[tuple(path)] = account

	return accounts


def isa_account_deposits(name, account):
	deposits = []
	guid = account.GetGUID().to_string()
	account_type = isa_account_type(account)

	for txn in account.GetSplitList():
		date = txn.parent.GetDate().date()
		year = tax_year(date)
		amount = Fraction()
		contribution = False

		for split in txn.parent.GetSplitList():
			if split.GetAccount().GetGUID().to_string() == guid:
				if split.GetValue().num() > 0:
					amount += split.GetValue().to_fraction()
			elif is_contribution_account(split.GetAccount()):
				if split.GetValue().num() < 0:
					contribution = True

		if amount and contribution:
			deposits.append(Deposit(year, date, name, amount, account_type))

	return deposits


def review_isa_year(year, deposits):
	allowance = ALLOWANCES[year]._asdict()
	contributions = defaultdict(Fraction)

	print(tabulate([[year]], tablefmt="heavy_outline"))

	rows = []
	for deposit in sorted(deposits):
		rows.append([deposit.date, frac2gbp(deposit.amount), deposit.account])
		contributions[deposit.type] += deposit.amount
		contributions["total"] += deposit.amount
	print(tabulate(rows, ["Date", "Amount", "Account"], tablefmt="rounded_outline", floatfmt=",.2f"))

	rows = []
	for account_type, type_name in {"cash": "Cash", "stocks": "S&S", "total": "Total"}.items():
		rows.append([
				type_name,
				frac2gbp(allowance[account_type]),
				frac2gbp(contributions[account_type]),
				frac2gbp(Fraction(allowance[account_type]) - contributions[account_type])
			])
	print(tabulate(rows, ["", "Allowance", "Contributions", "Remaining"], tablefmt="rounded_grid", floatfmt=",.2f"))


def review_isa_accounts(session):
	accounts = isa_accounts(session)
	deposits = defaultdict(list)

	for path, account in accounts.items():
		for deposit in isa_account_deposits(path2str(path), account):
			deposits[deposit.year].append(deposit)

	for year in sorted(deposits.keys()):
		review_isa_year(year, deposits[year])


if __name__ == "__main__":
	parser = argparse.ArgumentParser(description="GnuCash allowance reporting for UK Cash/S&S ISAs")
	parser.add_argument("-f", "--file", dest="file", required=True, help="GnuCash file")
	args = parser.parse_args()

	root = logging.getLogger()
	root.setLevel(level=logging.DEBUG)

	handler = logging.StreamHandler(sys.stdout)
	handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
	root.addHandler(handler)

	ok = True

	logging.debug("Start")

	before = datetime.today()
	session = gnucash.Session(args.file, mode=gnucash.SessionOpenMode.SESSION_READ_ONLY)
	after = datetime.today()
	logging.debug(f"File load time: {after - before}")

	try:
		review_isa_accounts(session)
	finally:
		session.end()
		session.destroy()

	logging.debug("Finish")

	sys.exit(0 if ok else 1)
