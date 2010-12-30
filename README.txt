==========
Transhette
==========

A simple Django application that  eases the translation process 
of your Django projects. 

Some of its features are:

* Database independent
* Reads and writes your project's gettext catalogs (po and mo files)
* Installed and uninstalled in under a minute
* Uses Django's admin interface CSS
* Translation suggestions via Google AJAX Language API 

Transhette was originally based on `rosetta
<http://code.google.com/p/django-rosetta/>`_ , which uses
`polib <http://code.google.com/p/polib/>`_. Both projects are distributed
under the MIT License. 

Transhette is distributed under the terms of the `GNU Lesser General Public
License <http://www.gnu.org/licenses/lgpl.html>`_.

Documentation
=============

Installation
------------

To install transhette:

1. Download the application and place the transhette folder anywhere in your Python path (your project directory is fine, 
   but anywhere else in your python path will do)
2. Add a ``transhette`` line to the ``INSTALLED_APPS`` in your project's ``settings.py``
3. Add a ``BASEDIR`` settings in your project's ``settings.py``, with a value like this::

    from os import path
    BASEDIR = path.dirname(path.abspath(__file__))

4. Add an URL entry to your project's urls.py, for example::

    from django.conf import settings
    if 'transhette' in settings.INSTALLED_APPS:
    urlpatterns += patterns('',
            url(r'^transhette/', include('transhette.urls')),
            )

Note: you can use whatever you wish as the URL prefix.

To uninstall transhette:

1. Comment out or remove the 'transhette' line in your INSTALLED_APPS
2. Comment out or remove the url inclusion 

Security
--------

Because transhette requires write access to some of the files in your Django project, access to the application is restricted to 
the administrator user only (as defined in your project's Admin interface)

If you wish to grant editing access to other users:

1. create a 'translators' group in your admin interface
2. add the user you wish to grant translating rights to this group 

Tutorial
--------

Start your Django development server and point your browser to the URL prefix you 
have chosen during the installation process. You will get to the file selection window. 

Select a file and translate each untranslated message. Whenever a new batch of messages 
is processed, transhette updates the corresponding django.po file and regenerates the 
corresponding mo file.

This means your project's labels will be translated right away, unfortunately you'll still 
have to restart the webserver for the changes to take effect.

If the webserver doesn't have write access on the catalog files an archive of the catalog 
files can be downloaded. 

There is a useful search box where you can enter keywords to find the desired string.

It is possible to filter the strings by their state "Only translated", "Only non-translated" 
and "Fuzzy". Fuzzy strings are the ones that have been automatically translated by ugettext, 
so be careful about them. You *should* check all Fuzzy Strings before saving your catalog. 
You can identify them in search results because they are yellow colored.

As well as you can download the catalog you are editing, you can also upload a catalog. 
The "Priority" option defines if the catalog that is going to be uploaded has priority
over the stored one. This means that *without* priority if transhette finds in the new catalog
an already translated string, it will respect the old translation. If you *enable priority*
the old value will be always overriden. Transhette manages empty translations as they don't 
exist.

Customization
-------------

TODO

Development
-----------

You can get the last bleeding edge version of transhette by doing
a checkout of its subversion repository. This way you can add it
as an external into your main project directory::

    svn checkout http://svnpub.yaco.es/djangoapps/transhette/trunk transhette

Bug reports, patches and suggestions are more than welcome. Just put
them in our Trac system and use the 'transhette' component when you fill
tickets::

    http://tracpub.yaco.es/djangoapps/

