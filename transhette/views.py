import os
import re
import datetime
import tempfile
import zipfile
import subprocess

from django.conf import settings
from django.contrib.auth.decorators import user_passes_test
from django.contrib.admin.util import unquote
from django.core.paginator import Paginator
from django.core.urlresolvers import reverse
from django.http import Http404, HttpResponseRedirect, HttpResponse
from django.template import RequestContext
from django.shortcuts import render_to_response
from django.utils import simplejson
from django.utils.encoding import smart_unicode, smart_str
from django.utils.translation import ugettext_lazy as _
from django.utils.translation import ugettext, get_language
from django.views.decorators.cache import cache_page, never_cache
from transhette.polib import pofile
from transhette.forms import (UpdatePoForm, UpdateConfirmationPoForm,
                           _get_path_file, _get_lang_by_file)
from transhette.poutil import find_pos, pagination_range, priority_merge, get_changes
from transhette.utils import get_setting
import transhette


def search_msg_id_in_other_pos(msg_list, lang, pofile_path):
    pofile_paths = find_pos(lang, include_djangos=get_setting('INCLUDE_DJANGOS'), include_transhette=get_setting('INCLUDE_TRANSHETTE'))
    pofiles = []
    for path in pofile_paths:
        pofiles.append(pofile(path))

    for msg in msg_list:
        for p in pofiles:
            valid_entry = None
            valid_catalog = p
            if p.fpath == pofile_path.fpath:
                is_valid = True
                break
            msgid = msg['message'].msgid
            entry = p.find(msgid)
            if entry:
                is_valid = False
                valid_entry = entry
                break
        msg.update({'is_valid': is_valid,
                    'valid_catalog': valid_catalog,
                    'valid_entry': valid_entry})
    return msg_list


def validate_format(pofile):
    errors = []
    handle, temp_file = tempfile.mkstemp()
    os.close(handle)
    pofile.save(temp_file)

    cmd = ['msgfmt', '--check-format', temp_file]
    process = subprocess.Popen(cmd, stderr=subprocess.PIPE)
    out, err = process.communicate()
    if process.returncode != 0:
        input_lines = open(temp_file, 'r').readlines()
        error_lines = err.strip().split('\n')
        # discard last line since it only says the number of fatal errors
        error_lines = error_lines[:-1]

        def format_error_line(line):
            parts = line.split(':')
            if len(parts) == 3:
                line_number = int(parts[1])
                text = input_lines[line_number - 1]
                return text + ': ' + parts[2]
            else:
                'Unknown error: ' + line

        errors = [format_error_line(line) for line in error_lines]

    os.unlink(temp_file)
    return errors


def reload_catalog_in_session(request, file_path=None):
    """ Reload transhette catalog in session """
    if file_path is None:
        file_path = request.session['transhette_i18n_fn']

    po = pofile(file_path)
    for i in range(len(po)):
        po[i].id = i
    request.session['transhette_i18n_fn'] = file_path
    request.session['transhette_i18n_pofile'] = po
    request.session['transhette_i18n_mtime'] = os.stat(file_path)[-2]


def reload_if_catalog_updated(request, polling=False):
    """ Compares modification time of catalog file with session last modification time, and reload if necessary
        This will avoid main concurrence problems """
    file_path = request.session['transhette_i18n_fn']
    file_mtime = os.stat(file_path)[-2]
    session_mtime = request.session.get('transhette_i18n_mtime')
    if polling:
        while session_mtime and file_mtime < session_mtime:
            file_mtime = os.stat(file_path)[-2]
            reload_catalog_in_session(request)
            session_mtime = request.session.get('transhette_i18n_mtime')
    else:
        if not session_mtime or file_mtime > session_mtime:
            reload_catalog_in_session(request)


def set_new_translation(request):
    """
    Post to include a new translation for a msgid
    """

    message='SOME ERRORS'
    if not request.POST:
        return None
    else:
        msgid = request.POST['msgid']
        msgstr = request.POST['msgstr']

    lang = get_language()
    pos = find_pos(lang, include_djangos=True, include_transhette=True)
    if pos:
        for file_po in pos:
            candidate = pofile(file_po)
            poentry = candidate.find(msgid)
            if poentry:
                selected_pofile = candidate
                poentry.msgstr = msgstr
                po_filename = file_po
                break
        version = transhette.get_version(True)
        format_errors = validate_format(selected_pofile)
        if not format_errors:
            try:
                selected_pofile.metadata['Last-Translator'] = str("%s %s <%s>" %(request.user.first_name, request.user.last_name, request.user.email))
                selected_pofile.metadata['X-Translated-Using'] = str("django-transhette %s" % transhette.get_version(False))
                selected_pofile.metadata['PO-Revision-Date'] = datetime.datetime.now().strftime('%Y-%m-%d %H:%M%z')
            except UnicodeDecodeError:
                pass
            selected_pofile.save()
            selected_pofile.save_as_mofile(po_filename.replace('.po', '.mo'))
            message='OK'

    return render_to_response('transhette/inline_demo_result.html',
                              {'message': message},
                              context_instance=RequestContext(request))


def inline_demo(request):
    """
    """
    return render_to_response('transhette/inline_demo.html',
                              {},
                              context_instance=RequestContext(request))


def do_restart(request, noresponse=False, with_ajax=False):
    """
    * "test" for a django instance (this do a touch over settings.py for reload)
    * "apache"
    * "httpd"
    * "wsgi"
    * "restart_script <script_path_name>"
    """
    if not with_ajax:
        sleep = 'sleep 5 && '
    else:
        sleep = ''
        noresponse=True

    if request.user.is_staff:
        reload_method = get_setting('AUTO_RELOAD_METHOD', default='test')

        if reload_method == 'test':
            os.system('%stouch settings.py &' % sleep)
        ## No RedHAT or similars
        elif reload_method == 'apache2':
            os.system('%ssudo apache2ctl restart &' % sleep)
        ## RedHAT, CentOS
        elif reload_method == 'httpd':
            os.system('%ssudo service httpd restart &' % sleep)

        elif reload_method.startswith('restart_script'):
            script = reload_method.split(" ")[1]
            os.system("%s%s $" % (sleep, script))

        if noresponse:
            return

        request.user.message_set.create(message=ugettext("Server restarted. Wait 10 seconds before checking translation"))

    return HttpResponseRedirect(request.environ['HTTP_REFERER'])


def home(request):
    """
    Displays a list of messages to be translated
    """

    def fix_nls(in_, out_):
        """Fixes submitted translations by filtering carriage returns and pairing
        newlines at the begging and end of the translated string with the original
        """
        if 0 == len(in_) or 0 == len(out_):
            return out_

        if "\r" in out_ and "\r" not in in_:
            out_=out_.replace("\r", '')

        if "\n" == in_[0] and "\n" != out_[0]:
            out_ = "\n" + out_
        elif "\n" != in_[0] and "\n" == out_[0]:
            out_ = out_.lstrip()
        if "\n" == in_[-1] and "\n" != out_[-1]:
            out_ = out_ + "\n"
        elif "\n" != in_[-1] and "\n" == out_[-1]:
            out_ = out_.rstrip()
        return out_

    version = transhette.get_version(True)
    if 'transhette_i18n_fn' in request.session:
        # if another translator has updated catalog... we will reload this
        reload_if_catalog_updated(request)

        transhette_i18n_fn = request.session.get('transhette_i18n_fn')
        transhette_i18n_pofile = request.session.get('transhette_i18n_pofile')
        transhette_i18n_native_pofile = request.session.get('transhette_i18n_native_pofile')
        transhette_i18n_lang_code = request.session.get('transhette_i18n_lang_code')
        transhette_i18n_lang_bidi = (transhette_i18n_lang_code in settings.LANGUAGES_BIDI)
        transhette_i18n_write = request.session.get('transhette_i18n_write', True)

        languages = []
        for language in settings.LANGUAGES:
            pos = find_pos(language[0])
            position = None
            for i in xrange(len(pos)):
                if transhette_i18n_pofile.fpath.replace('/%s/' % transhette_i18n_lang_code,
                                                     '/%s/' % language[0]) == pofile(pos[i]).fpath:
                    position = i
            if position is not None:
                languages.append((language[0], _(language[1]), position))

        # Retain query arguments
        query_arg = ''
        if 'query' in request.REQUEST:
            query_arg = '?query=%s' % request.REQUEST.get('query')
        if 'page' in request.GET:
            if query_arg:
                query_arg = query_arg + '&'
            else:
                query_arg = '?'
            query_arg = query_arg + 'page=%d' % int(request.GET.get('page'))


        if 'filter' in request.GET:
            if request.GET.get('filter') in ['untranslated', 'translated', 'both', 'fuzzy']:
                filter_ = request.GET.get('filter')
                request.session['transhette_i18n_filter'] = filter_
                return HttpResponseRedirect(reverse('transhette-home'))
        elif 'transhette_i18n_filter' in request.session:
            transhette_i18n_filter = request.session.get('transhette_i18n_filter')
        else:
            transhette_i18n_filter = 'both'

        if '_next' in request.POST:
            rx=re.compile(r'^m_([0-9]+)')
            rx_plural=re.compile(r'^m_([0-9]+)_([0-9]+)')
            file_change = False
            for k in request.POST.keys():
                if rx_plural.match(k):
                    id=int(rx_plural.match(k).groups()[0])
                    idx=int(rx_plural.match(k).groups()[1])
                    transhette_i18n_pofile[id].msgstr_plural[str(idx)] = fix_nls(transhette_i18n_pofile[id].msgid_plural[idx], request.POST.get(k))
                    file_change = True
                elif rx.match(k):
                    id=int(rx.match(k).groups()[0])
                    transhette_i18n_pofile[id].msgstr = fix_nls(transhette_i18n_pofile[id].msgid, request.POST.get(k))
                    file_change = True
                if file_change and 'fuzzy' in transhette_i18n_pofile[id].flags:
                    transhette_i18n_pofile[id].flags.remove('fuzzy')


            format_errors = validate_format(transhette_i18n_pofile)

            if file_change and transhette_i18n_write and not format_errors:
                reload_if_catalog_updated(request, polling=True)

                try:
                    transhette_i18n_pofile.metadata['Last-Translator'] = str("%s %s <%s>" %(request.user.first_name, request.user.last_name, request.user.email))
                    transhette_i18n_pofile.metadata['X-Translated-Using'] = str("django-transhette %s" % transhette.get_version(False))
                    transhette_i18n_pofile.metadata['PO-Revision-Date'] = datetime.datetime.now().strftime('%Y-%m-%d %H:%M%z')
                except UnicodeDecodeError:
                    pass
                try:
                    transhette_i18n_pofile.save()
                    transhette_i18n_pofile.save_as_mofile(transhette_i18n_fn.replace('.po', '.mo'))

                    # Try auto-reloading via the WSGI daemon mode reload mechanism
                    if get_setting('WSGI_AUTO_RELOAD') and\
                        'mod_wsgi.process_group' in request.environ and \
                        request.environ.get('mod_wsgi.process_group', None) and \
                        'SCRIPT_FILENAME' in request.environ and \
                        int(request.environ.get('mod_wsgi.script_reloading', '0')):
                            try:
                                os.utime(request.environ.get('SCRIPT_FILENAME'), None)
                            except OSError:
                                pass

                except:
                    request.session['transhette_i18n_write'] = False

                request.session['transhette_i18n_pofile'] = transhette_i18n_pofile
                request.session['transhette_i18n_native_pofile'] = transhette_i18n_native_pofile

                return HttpResponseRedirect(reverse('transhette-home') + query_arg)


        transhette_i18n_lang_name = _(request.session.get('transhette_i18n_lang_name'))
        transhette_i18n_lang_code = request.session.get('transhette_i18n_lang_code')
        transhette_i18n_native_lang_name = request.session.get('transhette_i18n_native_lang_name', '')
        transhette_i18n_native_lang_code = request.session.get('transhette_i18n_native_lang_code', '')


        if 'query' in request.REQUEST and request.REQUEST.get('query', '').strip():
            query = request.REQUEST.get('query').strip()
            rx = re.compile(query, re.IGNORECASE)
            matched_entries = []
            for e in transhette_i18n_pofile:
                entry_text = smart_unicode(e.msgstr) + smart_unicode(e.msgid)
                if get_setting('SEARCH_INTO_OCCURRENCES'):
                    entry_text += u''.join([o[0] for o in e.occurrences])
                if rx.search(entry_text):
                    matched_entries.append(e)
            for e in transhette_i18n_native_pofile:
                entry_text = smart_unicode(e.msgstr) + smart_unicode(e.msgid)
                if get_setting('SEARCH_INTO_OCCURRENCES'):
                    entry_text += u''.join([o[0] for o in e.occurrences])
                if rx.search(entry_text):
                    lang_entry = transhette_i18n_pofile.find(e.msgid)
                    if lang_entry and not lang_entry in matched_entries:
                        matched_entries.append(lang_entry)
            pofile_to_paginate = matched_entries
        else:
            if transhette_i18n_filter == 'both':
                pofile_to_paginate = transhette_i18n_pofile

            elif transhette_i18n_filter == 'untranslated':
                pofile_to_paginate = transhette_i18n_pofile.untranslated_entries()

            elif transhette_i18n_filter == 'translated':
                pofile_to_paginate = transhette_i18n_pofile.translated_entries()

            elif transhette_i18n_filter == 'fuzzy':
                pofile_to_paginate = transhette_i18n_pofile.fuzzy_entries()

        if get_setting('SHOW_NATIVE_LANGUAGE') and transhette_i18n_native_pofile:
            to_paginate = [dict(message=message, native_message=transhette_i18n_native_pofile.find(message.msgid)) \
                            for message in pofile_to_paginate]
        else:
            to_paginate = [dict(message=message) for message in pofile_to_paginate]

        paginator = Paginator(to_paginate, get_setting('MESSAGES_PER_PAGE'))

        if 'page' in request.GET and int(request.GET.get('page')) <= paginator.num_pages and int(request.GET.get('page')) > 0:
            page = int(request.GET.get('page'))
        else:
            page = 1

        if get_setting('SHOW_NATIVE_LANGUAGE') and transhette_i18n_lang_code != transhette_i18n_native_lang_code:
            default_column_name = True
        else:
            default_column_name = False

        message_list = paginator.page(page).object_list
        message_list = search_msg_id_in_other_pos(message_list, transhette_i18n_lang_code, transhette_i18n_pofile)
        needs_pagination = paginator.num_pages > 1
        if needs_pagination:
            if paginator.num_pages >= 10:
                page_range = pagination_range(1, paginator.num_pages, page)
            else:
                page_range = range(1, 1 + paginator.num_pages)
        ADMIN_MEDIA_PREFIX = settings.ADMIN_MEDIA_PREFIX
        ENABLE_TRANSLATION_SUGGESTIONS = get_setting('ENABLE_TRANSLATION_SUGGESTIONS')
        return render_to_response('transhette/pofile.html', locals(),
            context_instance=RequestContext(request))


    else:
        return list_languages(request)


@user_passes_test(lambda user: can_translate(user))
def restart_server(request):
    """
    Restart web server
    """
    if request.method == 'POST':
        do_restart(request, noresponse=True)
        request.user.message_set.create(message=ugettext("Server restarted. Wait 10 seconds before checking translation"))
        return HttpResponseRedirect(reverse('transhette-home'))
    ADMIN_MEDIA_PREFIX = settings.ADMIN_MEDIA_PREFIX
    return render_to_response('transhette/confirm_restart.html', locals(), context_instance=RequestContext(request))

home = user_passes_test(lambda user: can_translate(user), settings.LOGIN_URL)(home)
home = never_cache(home)


def download_file(request):
    # original filename
    transhette_i18n_fn=request.session.get('transhette_i18n_fn', None)
    # in-session modified catalog
    transhette_i18n_pofile = request.session.get('transhette_i18n_pofile', None)
    # language code
    transhette_i18n_lang_code = request.session.get('transhette_i18n_lang_code', None)

    if not transhette_i18n_lang_code or not transhette_i18n_pofile or not transhette_i18n_fn:
        return HttpResponseRedirect(reverse('transhette-home'))
    try:
        if len(transhette_i18n_fn.split('/')) >= 5:
            offered_fn = '_'.join(transhette_i18n_fn.split('/')[-5:])
        else:
            offered_fn = transhette_i18n_fn.split('/')[-1]
        # filenames
        tmpdir=tempfile.gettempdir()
        zip_fn = str(os.path.join(tmpdir, '%s.%s.zip' % (offered_fn, transhette_i18n_lang_code)))
        po_fn = str(os.path.join(tmpdir, transhette_i18n_fn.split('/')[-1]))
        mo_fn = str(po_fn.replace('.po', '.mo')) # not so smart, huh
        transhette_i18n_pofile.save(po_fn)
        transhette_i18n_pofile.save_as_mofile(mo_fn)
        zf = zipfile.ZipFile(zip_fn, 'w')
        zf.write(po_fn, str(po_fn.split('/')[-1]))
        zf.write(mo_fn, str(mo_fn.split('/')[-1]))
        zf.close()

        response = HttpResponse(file(zip_fn).read())
        response['Content-Disposition'] = 'attachment; filename=%s.%s.zip' %(offered_fn, transhette_i18n_lang_code)
        response['Content-Type'] = 'application/x-zip'

        os.unlink(zip_fn)
        os.unlink(po_fn)
        os.unlink(mo_fn)

        return response
    except Exception, e:
        return HttpResponseRedirect(reverse('transhette-home'))
        #return HttpResponse(e, mimetype="text/plain")
download_file=user_passes_test(lambda user: can_translate(user), '/admin/')(download_file)
download_file=never_cache(download_file)


def list_languages(request):
    """
    Lists the languages for the current project, the gettext catalog files
    that can be translated and their translation progress
    """
    languages = []
    do_django = 'django' in request.GET or get_setting('INCLUDE_DJANGOS')
    do_transhette = 'transhette' in request.GET or get_setting('INCLUDE_TRANSHETTE')
    has_pos = False
    for language in settings.LANGUAGES:
        pos = find_pos(language[0], include_djangos=do_django, include_transhette=do_transhette)
        has_pos = has_pos or len(pos)
        languages.append(
            (language[0],
            _(language[1]),
            [(os.path.realpath(l), pofile(l)) for l in pos],
            )
        )
    ADMIN_MEDIA_PREFIX = settings.ADMIN_MEDIA_PREFIX
    version = transhette.get_version(True)
    return render_to_response('transhette/languages.html', locals(), context_instance=RequestContext(request))
list_languages=user_passes_test(lambda user: can_translate(user), '/admin/')(list_languages)
list_languages=never_cache(list_languages)


def lang_sel(request, langid, idx):
    """
    Selects a file to be translated
    """
    if langid not in [l[0] for l in settings.LANGUAGES]:
        raise Http404
    else:

        do_django = 'django' in request.GET or get_setting('INCLUDE_DJANGOS')
        do_transhette = 'transhette' in request.GET or get_setting('INCLUDE_TRANSHETTE')

        request.session['transhette_i18n_lang_code'] = langid
        request.session['transhette_i18n_lang_name'] = str([l[1] for l in settings.LANGUAGES if l[0] == langid][0]).decode('utf-8')
        file_ = find_pos(langid, include_djangos=do_django, include_transhette=do_transhette)[int(idx)]

        reload_catalog_in_session(request, file_)

        # Retain query arguments
        query_arg = ""
        if 'query' in request.REQUEST:
            query_arg = '?query=%s' % request.REQUEST.get('query')
        if 'page' in request.GET:
            if query_arg:
                query_arg = query_arg + '&'
            else:
                query_arg = '?'
            query_arg = query_arg + 'page=%d' % int(request.GET.get('page'))


        if get_setting('SHOW_NATIVE_LANGUAGE'):
            native_lang = get_setting('FORCE_NATIVE_LANGUAGE_TO', default=get_language())
            request.session['transhette_i18n_native_lang_code'] = native_lang
            request.session['transhette_i18n_native_lang_name'] = str([l[1] for l in settings.LANGUAGES if l[0] == native_lang][0]).decode('utf-8')
            file_locale_path = file_.split(os.path.sep)
            file_locale_path[-3] = native_lang
            native_file_ = os.path.sep.join(file_locale_path)
            if os.path.isfile(native_file_):
                native_po = pofile(native_file_)
                for i in range(len(native_po)):
                    native_po[i].id = i

                request.session['transhette_i18n_native_pofile'] = native_po

        try:
            os.utime(file_, None)
            request.session['transhette_i18n_write'] = True
        except OSError:
            request.session['transhette_i18n_write'] = False
        return HttpResponseRedirect(reverse('transhette-home') + query_arg)
lang_sel=user_passes_test(lambda user: can_translate(user), '/admin/')(lang_sel)
lang_sel=never_cache(lang_sel)


def can_translate(user):
    if not user.is_authenticated():
        return False
    elif user.is_superuser or user.is_staff:
        return True
    else:
        try:
            from django.contrib.auth.models import Group
            translators = Group.objects.get(name='translators')
            return translators in user.groups.all()
        except Group.DoesNotExist:
            return False


def update_catalogue(request, no_confirmation=False):
    return update(request, catalogue=True, no_confirmation=no_confirmation)


def update(request, catalogue=False, no_confirmation=False):
    data = None
    files = None
    if request.method == 'POST':
        data = request.POST
        files = request.FILES

    pofile = None
    if catalogue:
        pofile = request.session.get('transhette_i18n_pofile')

    form = UpdatePoForm(pofile=pofile, data=data, files=files)

    if form.is_valid():
        po_tmp, po_dest_file, priority = form.save_temporal_file()
        if no_confirmation:
            merge(po_tmp, po_dest_file, priority)
            redirect_to = reverse('transhette.views.home')
        else:
            request.session['transhette_update_confirmation'] = {
                'po_tmp': po_tmp.fpath,
                'po_dest_file': po_dest_file.fpath,
                'priority': priority,
                'filename': form.cleaned_data['file'].name,
                'lang': _get_lang_by_file(po_dest_file.fpath),
            }

            redirect_to = reverse('transhette.views.update_confirmation')
        return HttpResponseRedirect(redirect_to)
    return render_to_response('transhette/update_file.html',
                              {'form': form,
                              'ADMIN_MEDIA_PREFIX': settings.ADMIN_MEDIA_PREFIX},
                              context_instance=RequestContext(request))


def update_confirmation(request):
    data = None
    if request.method == 'POST':
        data = request.POST

    form = UpdateConfirmationPoForm(data=data)
    up_conf = request.session.get('transhette_update_confirmation')
    priority = up_conf['priority']
    filename = up_conf['filename']
    pofile_tmp = pofile(up_conf['po_tmp'])
    pofile_dest_file = pofile(up_conf['po_dest_file'])

    if form.is_valid():
        priority = up_conf['priority']
        merge(pofile_tmp, pofile_dest_file, priority)
        redirect_to = reverse('transhette.views.home')
        return HttpResponseRedirect(redirect_to)
    else:
        lang = up_conf['lang']
        list_lang = find_pos(lang, include_djangos=False, include_transhette=False)
        lang_index = list_lang.index(up_conf['po_dest_file'])
        posible_path = _get_path_file(pofile_tmp, filename)
        news_entries, changes_entries = get_changes(pofile_tmp,
                                                   pofile_dest_file, priority)
    return render_to_response('transhette/update_confirmation.html',
                            {'form': form,
                             'news_entries': news_entries,
                             'changes_entries': changes_entries,
                             'po_dest_file': up_conf['po_dest_file'],
                             'priority': priority,
                             'posible_path': posible_path,
                             'lang': lang,
                             'lang_index': lang_index,
                             'ADMIN_MEDIA_PREFIX': settings.ADMIN_MEDIA_PREFIX},
                            context_instance=RequestContext(request))


def merge(po_tmp, po_dest_file, priority):
    po_tmp = pofile(po_tmp.fpath)
    priority_merge(po_dest_file, po_tmp, priority)


@cache_page(60 * 60 * 24)
def translation_conflicts(request):
    """ Returns a conflict msgid list. Same msgstr translations from different msgids """
    locale_path = os.path.join(settings.BASEDIR, 'locale')
    po_dict = {}
    # fill pofile_dict
    for lang, lang_name in settings.LANGUAGES:
        po = pofile(os.path.join(locale_path, lang, 'LC_MESSAGES', 'django.po'))
        po_dict[lang] = po
        # reference po file catalog. used to find conflicts
        main_po = po_dict['es']
        msgstr_list = [entry.msgstr for entry in main_po]
        msgid_list = [entry.msgid for entry in main_po]

    conflicts = []
    for msgstr in msgstr_list:
        indexes = []
        index = -1
        try:
            while True:
                index = msgstr_list.index(msgstr, index+1)
                entry = main_po.find(msgid_list[index])
                if entry.translated() and not entry.msgid_plural:
                    indexes.append(index)
        except ValueError:
            pass
        if len(indexes) == 0:
            continue # not present. usually msgstr was a database value
        elif len(indexes) > 1:
            # conflict happends. two or more msgid are translated into same msgstr
            conflict = {}
            conflict['msgstr'] = msgstr
            conflict['conflict_list'] = []
            for i in indexes:
                msgid = msgid_list[i]
                main_entry = main_po.find(msgid)
                item = {
                    'msgid': msgid,
                    'entries': [],
                    'occurrences': [],
                }
                for lang, po in po_dict.items():
                    entry = po.find(msgid)
                    if entry.translated():
                        item['entries'].append(
                            {'lang': lang, 'entry': entry},
                        )
                for occurrence in main_entry.occurrences:
                    item['occurrences'].append(
                        {'file': occurrence[0], 'line': occurrence[1]},
                    )
                conflict['conflict_list'].append(item)
            conflicts.append(conflict)
    return render_to_response('transhette/translation_conflicts.html',
                              {'conflicts': conflicts,
                               'ADMIN_MEDIA_PREFIX': settings.ADMIN_MEDIA_PREFIX},
                              context_instance=RequestContext(request))


def change_catalogue(request):
    new_catalog = request.GET.get('catalog', None)
    if not new_catalog:
        return HttpResponseRedirect(reverse('transhette-home'))
    reload_catalog_in_session(request, file_path=unquote(new_catalog))
    entry_id = request.GET.get('entry_id', None)
    if entry_id:
        query_arg = '?query=%s' % entry_id
    else:
        query_arg = ''
    return HttpResponseRedirect(reverse('transhette-home') + query_arg)


def ajax(request):

    def fix_nls(in_, out_):
        """Fixes submitted translations by filtering carriage returns and pairing
        newlines at the begging and end of the translated string with the original
        """
        if 0 == len(in_) or 0 == len(out_):
            return out_

        if "\r" in out_ and "\r" not in in_:
            out_=out_.replace("\r", '')

        if "\n" == in_[0] and "\n" != out_[0]:
            out_ = "\n" + out_
        elif "\n" != in_[0] and "\n" == out_[0]:
            out_ = out_.lstrip()
        if "\n" == in_[-1] and "\n" != out_[-1]:
            out_ = out_ + "\n"
        elif "\n" != in_[-1] and "\n" == out_[-1]:
            out_ = out_.rstrip()
        return out_

    catalog = request.GET.get('catalog', None)
    translation = request.GET.get('translation', None)
    if not translation:
        translation = {}
        for key, value in request.GET.items():
            if key.startswith('translation_'):
                translation[key.replace('translation_', '')]=value
    msgid = request.GET.get('msgid', None)
    try:
        po_file = pofile(catalog)
        entry = po_file.find(msgid)
    except:
        po_file = None
        entry = None
    if not catalog or not translation or not msgid\
       or not po_file or not entry:
        raise Http404

    saved = False
    if isinstance(translation, dict):
        for key, item in translation.items():
            entry.msgstr_plural[key] = fix_nls(entry.msgid_plural, item)
    else:
        entry.msgstr = fix_nls(entry.msgid, translation)
    if 'fuzzy' in entry.flags:
        entry.flags.remove('fuzzy')
    transhette_i18n_write = request.session.get('transhette_i18n_write', True)
    format_errors = validate_format(po_file)
    if transhette_i18n_write and not format_errors:
        try:
            po_file.metadata['Last-Translator'] = smart_str("%s %s <%s>" %(request.user.first_name, request.user.last_name, request.user.email))
            po_file.metadata['X-Translated-Using'] = str("django-transhette %s" % transhette.get_version(False))
            po_file.metadata['PO-Revision-Date'] = datetime.datetime.now().strftime('%Y-%m-%d %H:%M%z')
        except UnicodeDecodeError:
            pass
        try:
            po_file.save()
            po_file.save_as_mofile(po_file.fpath.replace('.po', '.mo'))
            saved = True
        except:
            pass

    json_dict = simplejson.dumps({'saved': saved,
                                  'translation': translation})
    return HttpResponse(json_dict, mimetype='text/javascript')


def ajax_restart(request):
    json_dict = simplejson.dumps({'restarting': True})
    do_restart(request, noresponse=True, with_ajax=True)
    return HttpResponse(json_dict, mimetype='text/javascript')


def ajax_is_wakeup(request):
    json_dict = simplejson.dumps({'wakeup': True})
    return HttpResponse(json_dict, mimetype='text/javascript')
