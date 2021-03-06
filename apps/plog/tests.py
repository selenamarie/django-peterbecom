import os
import re
import datetime
from urlparse import urlparse
from django.contrib.auth.models import User
from django.core.urlresolvers import reverse
from django.conf import settings
from django.test import TestCase
from apps.plog.models import BlogItem, BlogComment, Category, BlogFile
from apps.plog.utils import utc_now
from apps.redisutils import get_redis_connection


class PlogTestCase(TestCase):
    def setUp(self):
        self.redis = get_redis_connection()
        self.redis.flushdb()

    def _login(self):
        admin = User.objects.create(
          username='admin',
          is_staff=True
        )
        admin.set_password('secret')
        admin.save()
        assert self.client.login(username='admin', password='secret')
        return admin

    def test_blog_post_caching(self):
        blog = BlogItem.objects.create(
          oid='some-longish-test-post',
          title='TITLEX',
          text='BLABLABLA',
          display_format='structuredtext',
          pub_date=utc_now() - datetime.timedelta(seconds=10),
        )
        url = reverse('blog_post', args=[blog.oid])

        import apps.plog.views
        old_render = apps.plog.views.render
        from django.shortcuts import render as django_render
        render_counts = []
        def mocked_render(*a, **k):
            render_counts.append(1)
            return django_render(*a, **k)
        apps.plog.views.render = mocked_render
        try:
            response = self.client.get(url)
            self.assertTrue(blog.title in response.content)
            assert '0 comments' in response.content
            response = self.client.get(url)
            assert '0 comments' in response.content

            comment1 = BlogComment.objects.create(
              comment="textext",
              blogitem=blog,
              approved=True,
              add_date=utc_now() + datetime.timedelta(seconds=1),
            )
            response = self.client.get(url)
            assert '1 comment' in response.content
        finally:
            apps.plog.views.render = old_render

        assert len(render_counts) == 2

        self.assertTrue(self.redis.zrange('plog:hits', 0, -1, withscores=True),
                        [('/plog/some-longish-test-post', 5.0)])
        self.assertTrue(self.redis.zrange('plog:misses', 0, -1, withscores=True),
                        [('/plog/some-longish-test-post', 1.0)])

    def test_text_rendering_with_images(self):
        blog = BlogItem.objects.create(
          oid='myoid',
          title='TITLEX',
          text="""
          "image.png":/plog/myoid/image.png
          and *this*
          """,
          display_format='structuredtext',
          pub_date=utc_now() - datetime.timedelta(seconds=10),
        )
        url = reverse('blog_post', args=[blog.oid])
        response = self.client.get(url)
        content = response.content.split('id="post"')[1].split('</section')[0]
        self.assertTrue('<em>this</em>' in content)
        regex_str = ('/CONTENTCACHE-\d+%s' %
                     (re.escape('/plog/myoid/image.png'),))

        self.assertTrue(re.findall(regex_str, content))

        old = settings.STATIC_URL
        settings.STATIC_URL = '//some.cdn.com/'
        try:
            blog.text_rendered = ''
            blog.save()
            response = self.client.get(url)
            content = response.content.split('id="post"')[1].split('</section')[0]
            regex_str = ('%sCONTENTCACHE-\d+%s' %
                     (settings.STATIC_URL, re.escape('/plog/myoid/image.png')))
            self.assertTrue(re.findall(regex_str, content))
        finally:
            settings.STATIC_URL = old

    def test_preview_post(self):
        cat = Category.objects.create(name="MyCategory")
        self._login()
        url = reverse('plog_preview_post')
        data = {
          'title': 'Some <script> TITLE',
          'text': 'This is\n*great*\nin `verbatim`',
          'display_format': 'markdown',
          'pub_date': datetime.datetime.now().strftime('%Y-%m-%d'),
          'categories[]': str(cat.pk),
        }
        response = self.client.post(url, data)
        self.assertTrue('Some &lt;script&gt; TITLE' in response.content)
        self.assertTrue('This is<br' in response.content)
        self.assertTrue('<em>great</em>' in response.content)
        self.assertTrue('<code>verbatim</code>' in response.content)

        data['text'] = """This is

```python
def foo():
    return None
```

code"""

        response = self.client.post(url, data)
        self.assertTrue('<div class="highlight">' in response.content)
        self.assertTrue('<span class="k">def</span>' in response.content)

    def test_postmark_inbound(self):
        here = os.path.dirname(__file__)
        filepath = os.path.join(here, 'raw_data.1333828973.78.json')
        url = reverse('inbound_email')
        json_content = open(filepath).read()
        response = self.client.post(url, data=json_content,
            content_type="application/json")
        self.assertEqual(response.status_code, 200)
        self.assertTrue("error" in response.content.lower())
        self.assertTrue("no hashkey defined in subject line"
                        in response.content.lower())

        post = BlogItem.objects.create(
          oid='some-longish-test-post',
          title='TITLEX',
          text='BLABLABLA',
          display_format='structuredtext',
          pub_date=utc_now() - datetime.timedelta(seconds=10),
        )
        hashkey = post.get_or_create_inbound_hashkey()
        json_content = json_content.replace('Test subject',
             '%s: Test Title' % hashkey)

        response = self.client.post(url, data=json_content,
            content_type="application/json")
        self.assertEqual(response.status_code, 200)
        self.assertTrue("OK" in response.content)
        self.assertTrue(BlogFile.objects.filter(blogitem=post))
        blogfile, = BlogFile.objects.filter(blogitem=post)
        self.assertEqual(blogfile.title, 'Test Title')
        self.assertTrue(blogfile.file.read())

    def test_old_redirects(self):
        blog = BlogItem.objects.create(
          oid='myoid',
          title='TITLEX',
          text="""
          ttest test
          """,
          display_format='structuredtext',
          pub_date=utc_now() - datetime.timedelta(seconds=10),
        )
        url = reverse('blog_post', args=[blog.oid])

        response = self.client.get(url)
        assert response.status_code == 200

        response = self.client.get(url, {'replypath': 'foo'})
        self.assertEqual(response.status_code, 301)
        self.assertEqual(urlparse(response['location']).path, url)
        self.assertTrue(not urlparse(response['location']).query)
