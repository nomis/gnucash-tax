Description
===========

gnucash_tax_gb_isa
------------------

Basic contribution/allowance reporting for UK Cash/Stocks & Shares ISAs.

ISA accounts need to have a description matching the regular expression:

* ``/(Closed )?(Cash|Stocks & Shares) ISA ?/``

Deposits from all non-ISA accounts will be assumed to be making contributions
unless they are:

* Income accounts with a name (or parent name) of:

  * "Dividends"
  * "Interest"

* Mutual Fund accounts
* Stock accounts

Other ISA types are not supported.
