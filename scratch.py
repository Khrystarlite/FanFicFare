from six.moves.urllib.parse import urlparse
from six.moves.urllib.error import HTTPError
from six import ensure_text
import re
from fanficfare.adapters import *
from fanficfare.adapters.base_adapter import BaseSiteAdapter
from fanficfare import writers, exceptions, configurable
from fanficfare.htmlcleanup import stripHTML
from io import StringIO

import configparser

from bs4 import BeautifulSoup, Tag
import ssl
from urllib.request import urlopen

# import prefs
def getSiteURLPattern():
    return r"https?://(www\.)?web\.archive\.org/web/\d+/.+"
def validateURL(url):
    return re.match(getSiteURLPattern(), url)

url = "https://web.archive.org/web/20151002073959/https://www.fanfiction.net/s/8588745/1/Sinnoh-Revamped"
# url = "https://web.archive.org/web"

test_URL = "https://www.fanfiction.net/s/7262793/1/Ashes-of-the-Past"
test_URL2 = "https://archiveofourown.org/works/24240892/chapters/58411231"
url2 = "https://web.archive.org/web/20210110032955/https://archiveofourown.org/works/24240892/chapters/58411231"

parsedUrl = urlparse(url)
host = parsedUrl.netloc
path = parsedUrl.path
# print(host)
# print(path[5:])
site = path.split('/')[3:]
internal_Site = '/'.join(site)
# print('/'.join(site))
getNormalStoryURL.__dummyconfig = configurable.Configuration(["test1.com"],"EPUB",lightweight=True)

# print('/'.join(parsedUrl.path.split('/')[3:]))


## List of registered site adapters.
__class_list = []
__domain_map = {}

for x in imports():
    if "fanficfare.adapters.adapter_" in x:
        #print x
        cls = sys.modules[x].getClass()
        __class_list.append(cls)
        for site in cls.getAcceptDomains():
            l = __domain_map.get(site,[])
            l.append(cls)
            __domain_map[site]=l




def imports():
    out = []
    for name, val in globals().items():
        if isinstance(val, types.ModuleType):
            out.append(val.__name__)
    return out

def _get_netloc_for(url):
    """
    docstring
    """
    fixedurl = re.sub(r"(?i)^[htp]+(s?)[:/]+",r"http\1://",url.strip())
    if fixedurl.startswith("//"):
        fixedurl = "http:%s"%url
    if not fixedurl.startswith("http"):
        fixedurl = "http://%s"%url

    ## remove any trailing '#' locations, except for #post-12345 for
    ## XenForo
    if not "#post-" in fixedurl:
        fixedurl = re.sub(r"#.*$","",fixedurl)
    
    return fixedurl

def _get_class_for(url):
    ## fix up leading protocol.
    # fixedurl = re.sub(r"(?i)^[htp]+(s?)[:/]+",r"http\1://",url.strip())
    # if fixedurl.startswith("//"):
    #     fixedurl = "http:%s"%url
    # if not fixedurl.startswith("http"):
    #     fixedurl = "http://%s"%url

    # ## remove any trailing '#' locations, except for #post-12345 for
    # ## XenForo
    # if not "#post-" in fixedurl:  
    #     fixedurl = re.sub(r"#.*$","",fixedurl)
    # parsedUrl = urlparse(fixedurl)
    # print(parsedUrl)
    # if parsedUrl.netloc.lower() == 'web.archive.org':
    #     # print(parsedUrl.path.split('/')[3:])
    #     domain = '/'.join(parsedUrl.path.split('/')[3:])
    # else:
    #     domain = parsedUrl.netloc.lower()    
    #     if( domain != parsedUrl.netloc ):
    #         fixedurl = fixedurl.replace(parsedUrl.netloc,domain)

    
    fixedurl = _get_netloc_for(url)
    parsedUrl = urlparse(fixedurl)
    domain = parsedUrl.netloc.lower()    

    if domain == 'web.archive.org' or domain == 'archive.org': 
        fixedurl = '/'.join(parsedUrl.path.split('/')[3:])
        parsedUrl = urlparse(_get_netloc_for(fixedurl))
        # domain = parsedUrl.netloc.lower()
    else: 
        if( domain != parsedUrl.netloc ):
            fixedurl = fixedurl.replace(parsedUrl.netloc,domain)
    print("domain:\t", domain)
    print("fixedurl:\t", fixedurl)
    clslst = _get_classlist_fromlist(domain)
    ## assumes all adapters for a domain will have www or not have www
    ## but not mixed.
    if not clslst and domain.startswith("www."):
        domain = domain.replace("www.","")
        #logger.debug("trying site:without www: "+domain)
        clslst = _get_classlist_fromlist(domain)
        fixedurl = re.sub(r"^http(s?)://www\.",r"http\1://",fixedurl)
    if not clslst:
        #logger.debug("trying site:www."+domain)
        clslst =_get_classlist_fromlist("www."+domain)
        fixedurl = re.sub(r"^http(s?)://",r"http\1://www.",fixedurl)

    cls = None
    if clslst: 
        if len(clslst) == 1:
            cls = clslst[0]
        elif len(clslst) > 1:
            for c in clslst:
                if c.getSiteURLFragment() in fixedurl:
                    cls = c
                    break

    if cls:
        fixedurl = cls.stripURLParameters(fixedurl)

    return (cls,fixedurl)

def _get_classlist_fromlist(domain):
    try:
        return __domain_map[domain]
    except KeyError:
        pass # return none.



def make_book():
    book = {}
    book['title'] = 'Unknown'
    book['author_sort'] = book['author'] = ['Unknown'] # list
    book['comments'] = '' # note this is the book comments.

    book['good'] = True
    book['status'] = 'Bad'
    book['showerror'] = True # False when NotGoingToDownload is
                                # not-overwrite / not-update / skip
                                # -- what some would consider 'not an
                                # error'
    book['calibre_id'] = None
    book['begin'] = None
    book['end'] = None
    book['comment'] = '' # note this is a comment on the d/l or update.
    book['url'] = ''
    book['site'] = ''
    book['series'] = ''
    book['added'] = False
    book['pubdate'] = None
    book['publisher'] = None
    return book

def set_book_url_and_comment(book,url):
    if not url:
        book['comment'] = _("No story URL found.")
        book['good'] = False
        book['icon'] = 'search_delete_saved.png'
        book['status'] = _('Not Found')
    else:
        # get normalized url or None.
        urlsitetuple = getNormalStoryURLSite(url)
        if urlsitetuple == None:
            # print("HIT")
            book['url'] = url
            book['comment'] = _("URL is not a valid story URL.")
            book['good'] = False
            book['icon']='dialog_error.png'
            book['status'] = _('Bad URL')
        else:
            (book['url'],book['site'])=urlsitetuple

def convert_urls_to_books(urls):
    books = []
    uniqueurls = set()
    for i, url in enumerate(urls):
        book = convert_url_to_book(url)
        if book['uniqueurl'] in uniqueurls: 
            book['good'] = False
            book['comment'] = _("Same story already included.")
            book['status']=_('Skipped')
        uniqueurls.add(book['uniqueurl'])
        book['listorder']=i # BG d/l jobs don't come back in order.
                            # Didn't matter until anthologies & 'marked' successes
        books.append(book)
    return books

def convert_url_to_book(url):
    book = make_book()
    # Allow chapter range with URL.
    # like test1.com?sid=5[4-6] or [4,6]
    # url,book['begin'],book['end'] = adapters.get_url_chapter_range(url)
    url,book['begin'],book['end'] = get_url_chapter_range(url)

    set_book_url_and_comment(book,url) # normalizes book[url]
    # for case of trying to download book by sections. url[1-5], url[6-10], etc.
    book['uniqueurl']="%s[%s-%s]"%(book['url'],book['begin'],book['end'])
    return book


def get_fff_personalini():
    return prefs['personal.ini']

def get_fff_config(url,fileform="epub",personalini=None):
    if not personalini:
        personalini = get_fff_personalini()
    sections=['unknown']
    try:
        sections = adapters.getConfigSectionsFor(url)
    except Exception as e:
        logger.debug("Failed trying to get ini config for url(%s): %s, using section %s instead"%(url,e,sections))
    configuration = Configuration(sections,fileform)
    configuration.readfp(StringIO(ensure_text(get_resources("plugin-defaults.ini"))))
    configuration.readfp(StringIO(ensure_text(personalini)))

    return configuration


def doExtractChapterUrlsAndMetadata(url,get_cover=True):

    # fetch the chapter.  From that we will get almost all the
    # metadata and chapter list

    logger.debug("URL: "+url)

    # use BeautifulSoup HTML parser to make everything easier to find.
    try:
        data = _fetchUrl(url)
        #logger.debug("\n===================\n%s\n===================\n"%data)
        soup = make_soup(data)
    except HTTPError as e:
        if e.code == 404:
            raise exceptions.StoryDoesNotExist(url)
        else:
            raise e

    if "Unable to locate story" in data or "Story Not Found" in data:
        raise exceptions.StoryDoesNotExist(url)

    # some times "Chapter not found...", sometimes "Chapter text
    # not found..." or "Story does not have any chapters"
    if "Please check to see you are not using an outdated url." in data:
        raise exceptions.FailedToDownload("Error downloading Chapter: %s!  'Chapter not found. Please check to see you are not using an outdated url.'" % url)

    if getConfig('check_next_chapter'):
        try:
            ## ffnet used to have a tendency to send out update
            ## notices in email before all their servers were
            ## showing the update on the first chapter.  It
            ## generates another server request and doesn't seem
            ## to be needed lately, so now default it to off.
            try:
                chapcount = len(soup.find('select', { 'name' : 'chapter' } ).findAll('option'))
            # get chapter part of url.
            except:
                chapcount = 1
            tryurl = "https://%s/s/%s/%d/"%(getSiteDomain(),
                                            story.getMetadata('storyId'),
                                            chapcount+1)
            logger.debug('=Trying newer chapter: %s' % tryurl)
            newdata = _fetchUrl(tryurl)
            if "not found. Please check to see you are not using an outdated url." not in newdata \
                    and "This request takes too long to process, it is timed out by the server." not in newdata:
                logger.debug('=======Found newer chapter: %s' % tryurl)
                soup = make_soup(newdata)
        except HTTPError as e:
            if e.code == 503:
                raise e
        except Exception as e:
            logger.warning("Caught an exception reading URL: %s Exception %s."%(unicode(url),unicode(e)))
            pass

    # Find authorid and URL from... author url.
    a = soup.find('a', href=re.compile(r"^/u/\d+"))
    story.setMetadata('authorId',a['href'].split('/')[2])
    story.setMetadata('authorUrl','https://'+host+a['href'])
    story.setMetadata('author',a.string)

    ## Pull some additional data from html.

    ## ffnet shows category two ways
    ## 1) class(Book, TV, Game,etc) >> category(Harry Potter, Sailor Moon, etc)
    ## 2) cat1_cat2_Crossover
    ## For 1, use the second link.
    ## For 2, fetch the crossover page and pull the two categories from there.
    pre_links = soup.find('div',{'id':'pre_story_links'})
    categories = pre_links.findAll('a',{'class':'xcontrast_txt'})
    #print("xcontrast_txt a:%s"%categories)
    if len(categories) > 1:
        # Strangely, the ones with *two* links are the
        # non-crossover categories.  Each is in a category it        # of Book, Movie, etc.
        story.addToList('category',stripHTML(categories[1]))
    elif 'Crossover' in categories[0]['href']:
        caturl = "https://%s%s"%(getSiteDomain(),categories[0]['href'])
        catsoup = make_soup(_fetchUrl(caturl))
        found = False
        for a in catsoup.findAll('a',href=re.compile(r"^/crossovers/.+?/\d+/")):
            story.addToList('category',stripHTML(a))
            found = True
        if not found:
            # Fall back.  I ran across a story with a Crossver
            # category link to a broken page once.
            # http://www.fanfiction.net/s/2622060/1/
            # Naruto + Harry Potter Crossover
            logger.info("Fall back category collection")
            for c in stripHTML(categories[0]).replace(" Crossover","").split(' + '):
                story.addToList('category',c)

    a = soup.find('a', href=re.compile(r'https?://www\.fictionratings\.com/'))
    rating = a.string
    if 'Fiction' in rating: # if rating has 'Fiction ', strip that out for consistency with past.
        rating = rating[8:]

    story.setMetadata('rating',rating)

    # after Rating, the same bit of text containing id:123456 contains
    # Complete--if completed.
    gui_table1i = soup.find('div',{'id':'content_wrapper_inner'})

    story.setMetadata('title', stripHTML(gui_table1i.find('b'))) # title appears to be only(or at least first) bold tag in gui_table1i

    summarydiv = gui_table1i.find('div',{'style':'margin-top:2px'})
    if summarydiv:
        setDescription(url,stripHTML(summarydiv))


    grayspan = gui_table1i.find('span', {'class':'xgray xcontrast_txt'})
    # for b in grayspan.findAll('button'):
    #     b.extract()
    metatext = stripHTML(grayspan).replace('Hurt/Comfort','Hurt-Comfort')
    #logger.debug("metatext:(%s)"%metatext)

    if 'Status: Complete' in metatext:
        story.setMetadata('status', 'Completed')
    else:
        story.setMetadata('status', 'In-Progress')

    ## Newer BS libraries are discarding whitespace after tags now. :-/
    metalist = re.split(" ?- ",metatext)
    #logger.debug("metalist:(%s)"%metalist)

    # Rated: Fiction K - English - Words: 158,078 - Published: 02-04-11
    # Rated: Fiction T - English - Adventure/Sci-Fi - Naruto U. - Chapters: 22 - Words: 114,414 - Reviews: 395 - Favs: 779 - Follows: 835 - Updated: 03-21-13 - Published: 04-28-12 - id: 8067258

    # rating is obtained above more robustly.
    if metalist[0].startswith('Rated:'):
        metalist=metalist[1:]

    # next is assumed to be language.
    story.setMetadata('language',metalist[0])
    metalist=metalist[1:]

    # next might be genre.
    genrelist = metalist[0].split('/') # Hurt/Comfort already changed above.
    goodgenres=True
    for g in genrelist:
        #logger.debug("g:(%s)"%g)
        if g.strip() not in ffnetgenres:
            #logger.info("g not in ffnetgenres")
            goodgenres=False
    if goodgenres:
        story.extendList('genre',genrelist)
        metalist=metalist[1:]

    # Updated: <span data-xutime='1368059198'>5/8</span> - Published: <span data-xutime='1278984264'>7/12/2010</span>
    # Published: <span data-xutime='1384358726'>8m ago</span>
    dates = soup.findAll('span',{'data-xutime':re.compile(r'^\d+$')})
    if len(dates) > 1 :
        # updated get set to the same as published upstream if not found.
        story.setMetadata('dateUpdated',datetime.fromtimestamp(float(dates[0]['data-xutime'])))
    story.setMetadata('datePublished',datetime.fromtimestamp(float(dates[-1]['data-xutime'])))

    # Meta key titles and the metadata they go into, if any.
    metakeys = {
        # These are already handled separately.
        'Chapters':False,
        'Status':False,
        'id':False,
        'Updated':False,
        'Published':False,
        'Reviews':'reviews',
        'Favs':'favs',
        'Follows':'follows',
        'Words':'numWords',
        }

    chars_ships_list=[]
    while len(metalist) > 0:
        m = metalist.pop(0)
        if ':' in m:
            key = m.split(':')[0].strip()
            if key in metakeys:
                if metakeys[key]:
                    story.setMetadata(metakeys[key],m.split(':')[1].strip())
                continue
        # no ':' or not found in metakeys
        chars_ships_list.append(m)

    # all because sometimes chars can have ' - ' in them.
    chars_ships_text = (' - ').join(chars_ships_list)
    # print("chars_ships_text:%s"%chars_ships_text)
    # with 'pairing' support, pairings are bracketed w/o comma after
    # [Caspian X, Lucy Pevensie] Edmund Pevensie, Peter Pevensie
    story.extendList('characters',chars_ships_text.replace('[','').replace(']',',').split(','))

    l = chars_ships_text
    while '[' in l:
        story.addToList('ships',l[l.index('[')+1:l.index(']')].replace(', ','/'))
        l = l[l.index(']')+1:]

    if get_cover:
        # Try the larger image first.
        cover_url = ""
        try:
            img = soup.select_one('img.lazy.cimage')
            cover_url=img['data-original']
        except:
            img = soup.select_one('img.cimage:not(.lazy)')
            if img:
                cover_url=img['src']
        ## Nov 19, 2020, ffnet lazy cover images returning 0 byte
        ## files.
        logger.debug("cover_url:%s"%cover_url)

        authimg_url = ""
        if cover_url and getConfig('skip_author_cover'):
            authsoup = make_soup(_fetchUrl(story.getMetadata('authorUrl')))
            try:
                img = authsoup.select_one('img.lazy.cimage')
                authimg_url=img['data-original']
            except:
                img = authsoup.select_one('img.cimage')
                if img:
                    authimg_url=img['src']

            logger.debug("authimg_url:%s"%authimg_url)

            ## ffnet uses different sizes on auth & story pages, but same id.
            ## //ffcdn2012t-fictionpressllc.netdna-ssl.com/image/1936929/150/
            ## //ffcdn2012t-fictionpressllc.netdna-ssl.com/image/1936929/180/
            try:
                cover_id = cover_url.split('/')[4]
            except:
                cover_id = None
            try:
                authimg_id = authimg_url.split('/')[4]
            except:
                authimg_id = None

            ## don't use cover if it matches the auth image.
            if cover_id and authimg_id and cover_id == authimg_id:
                cover_url = None

        if cover_url:
            setCoverImage(url,cover_url)


    # Find the chapter selector
    select = soup.find('select', { 'name' : 'chapter' } )

    if select is None:
        # no selector found, so it's a one-chapter story.
        add_chapter(story.getMetadata('title'),url)
    else:
        allOptions = select.findAll('option')
        for o in allOptions:
            url = u'https://%s/s/%s/%s/' % ( getSiteDomain(),
                                                story.getMetadata('storyId'),
                                                o['value'])
            # just in case there's tags, like <i> in chapter titles.
            title = u"%s" % o
            title = re.sub(r'<[^>]+>','',title)
            add_chapter(title,url)


    return

def make_soup(self,data):
    '''
    Convenience method for getting a bs4 soup.  bs3 has been removed.
    '''

    ## html5lib handles <noscript> oddly.  See:
    ## https://bugs.launchpad.net/beautifulsoup/+bug/1277464
    ## This should 'hide' and restore <noscript> tags.
    data = data.replace("noscript>","fff_hide_noscript>")

    ## soup and re-soup because BS4/html5lib is more forgiving of
    ## incorrectly nested tags that way.
    soup = BeautifulSoup(data,'html5lib')
    soup = BeautifulSoup(unicode(soup),'html5lib')

    for ns in soup.find_all('fff_hide_noscript'):
        ns.name = 'noscript'

    return soup

def getNormalStoryURLSite(url):
    # print("getNormalStoryURLSite:%s"%url)
    if not getNormalStoryURL.__dummyconfig:
        getNormalStoryURL.__dummyconfig = configurable.Configuration(["test1.com"],"EPUB",lightweight=True)
    # pulling up an adapter is pretty low over-head.  If
    # it fails, it's a bad url.
    try:
        adapter = getAdapter(getNormalStoryURL.__dummyconfig,url)
        url = adapter.url
        site = adapter.getSiteDomain()
        del adapter
        return (url,site)
    except:
        return None



# print(book)
# config = get_fff_config(book)

# print(url) 
# print(internal_Site)
# print()
# print(_get_class_for(test_URL))
# print(_get_class_for(test_URL2))
# print()
print(_get_class_for(url))
# print(_get_class_for(url2))
# print(_get_class_for(internal_Site))
# print()
# print(convert_url_to_book(url))
# print(convert_url_to_book(internal_Site))
# print()
# url = "https://web.archive.org/web/20151002073959/https://www.fanfiction.net/s/8588745/1/Sinnoh-Revamped"
# # url = "https://web.archive.org/web"

# test_URL = "https://www.fanfiction.net/s/7262793/1/Ashes-of-the-Past"
# test_URL2 = "https://archiveofourown.org/works/24240892/chapters/58411231"
# url2 = "https://web.archive.org/web/20210110032955/https://archiveofourown.org/works/24240892/chapters/58411231"

# options={'fileform':'epub',
#                                      'collision':ADDNEW,
#                                      'updatemeta':True,
#                                      'bgmeta':False,
                                    #  'updateepubcover':True},


config = configparser.ConfigParser()
config2 = configparser.ConfigParser()
personal_init = config.read("calibre-plugin/plugin-example.ini")
config2.read("calibre-plugin/plugin-defaults.ini")
# for c in config2:
#     print(c) 
fileform = "epub"
sections = getConfigSectionsFor(url) 
# print(sections)
conf = configurable.Configuration(sections,fileform)
# conf.readfp(StringIO(ensure_text()))

for f in conf:
    print(f)


ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE

html = urlopen(url, context=ctx).read()
soup = BeautifulSoup(html, "html.parser")

# print(soup)

tags = soup('a')

# sumNum = 0
# for tag in tags:
#     # sumNum += int(tag.contents[0])
#     print(tag.contents)
# print(sumNum)