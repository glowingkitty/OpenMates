/**
 * App-store examples for the images skill.
 *
 * Captured from real Brave image search responses, trimmed to 4 images per query.
 */

export interface ImagesSearchStoreExample {
  id: string;
  query: string;
  query_translation_key?: string;
  provider: string;
  status: 'finished';
  results: Array<Record<string, unknown>>;
}

const examples: ImagesSearchStoreExample[] = [
  {
    "id": "store-example-images-search-1",
    "query": "Golden Gate Bridge at sunset",
    "query_translation_key": "settings.app_store_examples.images.search.1",
    "provider": "Brave Search",
    "status": "finished",
    "results": [
      {
        "title": "Golden gate bridge at sunset with a beautiful warm fog",
        "source_page_url": "https://stock.adobe.com/search?k=golden+gate+bridge+sunset",
        "image_url": "https://t3.ftcdn.net/jpg/16/21/48/10/360_F_1621481048_6D6tbExgmW4s0e3RL8e6FWHRVbEzAyZs.jpg",
        "thumbnail_url": "https://imgs.search.brave.com/uarSor2VWylwjFcQDYFwq3QDSD1IelteH3RzPszjTI4/rs:fit:500:0:1:0/g:ce/aHR0cHM6Ly90My5m/dGNkbi5uZXQvanBn/LzE2LzIxLzQ4LzEw/LzM2MF9GXzE2MjE0/ODEwNDhfNkQ2dGJF/eGdtVzRzMGUzUkw4/ZTZGV0hSVmJFekF5/WnMuanBn",
        "source": "stock.adobe.com",
        "favicon_url": "https://imgs.search.brave.com/ZxIJGoK8dKjPx3r6T5VEe1HXg5wLOSkejXoCy5fIufQ/rs:fit:32:32:1:0/g:ce/aHR0cDovL2Zhdmlj/b25zLnNlYXJjaC5i/cmF2ZS5jb20vaWNv/bnMvOTFhMDJkZGQ1/OWEwZTBhOGJjODU2/ZDcwNTQ1MzYyYmNm/NDlhYTY4Y2FhYjY4/MjYzNTgxMWUwM2Q3/YmJmZTQ2ZS9zdG9j/ay5hZG9iZS5jb20v"
      },
      {
        "title": "Waves crash near Fort Point beneath the Golden Gate Bridge at sunset.",
        "source_page_url": "https://www.sftravel.com/things-to-do/attractions/iconic-sf/golden-gate-bridge",
        "image_url": "https://www.sftravel.com/sites/default/files/styles/square_medium/public/2022-10/golden-gate-bridge-sunset-fort-point.jpg.webp?itok=8A1-xfpW",
        "thumbnail_url": "https://imgs.search.brave.com/mSXvJpRFdNsIdipP8SNXkJ5Bi8JuiNnEX8psxqHW0mk/rs:fit:500:0:1:0/g:ce/aHR0cHM6Ly93d3cu/c2Z0cmF2ZWwuY29t/L3NpdGVzL2RlZmF1/bHQvZmlsZXMvc3R5/bGVzL3NxdWFyZV9t/ZWRpdW0vcHVibGlj/LzIwMjItMTAvZ29s/ZGVuLWdhdGUtYnJp/ZGdlLXN1bnNldC1m/b3J0LXBvaW50Lmpw/Zy53ZWJwP2l0b2s9/OEExLXhmcFc",
        "source": "sftravel.com",
        "favicon_url": "https://imgs.search.brave.com/QY6jgH2_jyWAbOVO_WeJMaJ4y7NroO9Qwq71N0dqGGQ/rs:fit:32:32:1:0/g:ce/aHR0cDovL2Zhdmlj/b25zLnNlYXJjaC5i/cmF2ZS5jb20vaWNv/bnMvOGY1ZmEwYWU5/ZTI3ZWRhZGFiMDIw/OGU4ODk4OGYxYzhm/OWY2NWNiMWMyN2M4/NTk1N2FhNzJlODMy/NTBlMWJmOC93d3cu/c2Z0cmF2ZWwuY29t/Lw"
      },
      {
        "title": "a view of the golden gate bridge at sunset",
        "source_page_url": "https://unsplash.com/photos/a-view-of-the-golden-gate-bridge-at-sunset-GDljLNvdY_w",
        "image_url": "https://images.unsplash.com/photo-1643005842873-3855db918670?fm=jpg&q=60&w=3000&ixlib=rb-4.1.0&ixid=M3wxMjA3fDB8MHxwaG90by1wYWdlfHx8fGVufDB8fHx8fA==",
        "thumbnail_url": "https://imgs.search.brave.com/xbYXYOYo5xt7H0RaZTHvN03DYejDG-yKJh29wyikxfU/rs:fit:500:0:1:0/g:ce/aHR0cHM6Ly9pbWFn/ZXMudW5zcGxhc2gu/Y29tL3Bob3RvLTE2/NDMwMDU4NDI4NzMt/Mzg1NWRiOTE4Njcw/P2ZtPWpwZyZxPTYw/Jnc9MzAwMCZpeGxp/Yj1yYi00LjEuMCZp/eGlkPU0zd3hNakEz/ZkRCOE1IeHdhRzkw/Ynkxd1lXZGxmSHg4/ZkdWdWZEQjhmSHg4/ZkE9PQ",
        "source": "unsplash.com",
        "favicon_url": "https://imgs.search.brave.com/UFQasvzwLnO1phC8IRS6qXLb7mLVSbC00uaiLY8o2IQ/rs:fit:32:32:1:0/g:ce/aHR0cDovL2Zhdmlj/b25zLnNlYXJjaC5i/cmF2ZS5jb20vaWNv/bnMvZTgxODEwOTU5/NDQ5YzBjMmRhMmJk/Y2JmYzc1MDhlMDU5/MzI2ODYzMTlkYTRl/YzZjNWYwMjU2M2Y0/YzkxNDRkYS91bnNw/bGFzaC5jb20v"
      },
      {
        "title": "the golden gate bridge in san francisco at sunset",
        "source_page_url": "https://www.pinterest.com/ideas/golden-gate-bridge-sunset/914165937413/",
        "image_url": "https://i.pinimg.com/originals/fd/1f/1e/fd1f1ea6ff2d9325f9e454d3b877ae8e.jpg",
        "thumbnail_url": "https://imgs.search.brave.com/QXcc1N027KAbHEd4aIW7_cJG6MoBjSQ8faH-GSg1Gho/rs:fit:500:0:1:0/g:ce/aHR0cHM6Ly9pLnBp/bmltZy5jb20vb3Jp/Z2luYWxzL2ZkLzFm/LzFlL2ZkMWYxZWE2/ZmYyZDkzMjVmOWU0/NTRkM2I4NzdhZThl/LmpwZw",
        "source": "pinterest.com",
        "favicon_url": "https://imgs.search.brave.com/-h42ysf4Z1TVzWXJ_OIFNE0ITzUbcR1EHzme8pM24s0/rs:fit:32:32:1:0/g:ce/aHR0cDovL2Zhdmlj/b25zLnNlYXJjaC5i/cmF2ZS5jb20vaWNv/bnMvY2Y1ZmYzYzAx/ZTdjNDk1MTMwODVj/OWRlNTBlZTBmZWU5/Y2U1YzA2MGMwZmVj/ZWE5NmJjZjk2OGZi/MWZhNTY0Mi93d3cu/cGludGVyZXN0LmNv/bS8"
      }
    ]
  },
  {
    "id": "store-example-images-search-2",
    "query": "Minimalist Scandinavian interior design",
    "query_translation_key": "settings.app_store_examples.images.search.2",
    "provider": "Brave Search",
    "status": "finished",
    "results": [
      {
        "title": "Kitchen highlighting Scandinavian minimalist interior design",
        "source_page_url": "https://www.carlfriedrik.com/magazine/scandinavian-minimalism",
        "image_url": "https://cdn.builder.io/api/v1/image/assets/f908d2a4bd044e4d8f96b4ef79aa4d93/7862b86f4cae4ec3a50edb0370ddc27e?width=864",
        "thumbnail_url": "https://imgs.search.brave.com/diuOXBldT0XGmJ2ejvXHicnR_0d43UZvW6WM8a3rUzE/rs:fit:500:0:1:0/g:ce/aHR0cHM6Ly9jZG4u/YnVpbGRlci5pby9h/cGkvdjEvaW1hZ2Uv/YXNzZXRzL2Y5MDhk/MmE0YmQwNDRlNGQ4/Zjk2YjRlZjc5YWE0/ZDkzLzc4NjJiODZm/NGNhZTRlYzNhNTBl/ZGIwMzcwZGRjMjdl/P3dpZHRoPTg2NA",
        "source": "carlfriedrik.com",
        "favicon_url": "https://imgs.search.brave.com/aSclx9Bmo24hI7gHPx0CGITBAjvEqYCW7CC7ZsVe_qY/rs:fit:32:32:1:0/g:ce/aHR0cDovL2Zhdmlj/b25zLnNlYXJjaC5i/cmF2ZS5jb20vaWNv/bnMvZmI5ZmNmZDAw/NWJhNGYwZmFkZjNj/OWYxZGVlYTVkMDE2/MTAwYjViMTA0ODAz/ZDM0YjM1OTE1MWU0/MGMyYzQ1Ni93d3cu/Y2FybGZyaWVkcmlr/LmNvbS8"
      },
      {
        "title": "Minimalist style interior design",
        "source_page_url": "https://sfd-craft.com/whats-the-difference-between-scandinavian-minimalist-design/",
        "image_url": "https://sfd-craft.com/wp-content/uploads/2022/05/2_difference-between-Scandinavian-Minimalist-design-SFD-pic.jpg",
        "thumbnail_url": "https://imgs.search.brave.com/BSsgas-7ORNgDRYbJHXOmyQEzLWWRFKoLrlNU7VhT5M/rs:fit:500:0:1:0/g:ce/aHR0cHM6Ly9zZmQt/Y3JhZnQuY29tL3dw/LWNvbnRlbnQvdXBs/b2Fkcy8yMDIyLzA1/LzJfZGlmZmVyZW5j/ZS1iZXR3ZWVuLVNj/YW5kaW5hdmlhbi1N/aW5pbWFsaXN0LWRl/c2lnbi1TRkQtcGlj/LmpwZw",
        "source": "sfd-craft.com",
        "favicon_url": "https://imgs.search.brave.com/zwIt_vE6RXak3fI9G5lHMj27DWB-2ZdQ8zCLb7bnzTQ/rs:fit:32:32:1:0/g:ce/aHR0cDovL2Zhdmlj/b25zLnNlYXJjaC5i/cmF2ZS5jb20vaWNv/bnMvZTFkNTAyNmE3/YjNhMmMwZjg2ZGJi/YzE1MTg1ZTFlYjA1/NzJlZDUxNTRiOTAz/YWUzZGFkMzRlODY3/NmNjNTdjNy9zZmQt/Y3JhZnQuY29tLw"
      },
      {
        "title": "",
        "source_page_url": "https://www.designstudio210.com/interior-spaces/scandinavian-interior-design/scandinavian-minimalist-interior-design/",
        "image_url": "https://www.designstudio210.com/wp-content/uploads/2023/08/scandinavian-minimalistic-interior-design-white-walls.jpeg",
        "thumbnail_url": "https://imgs.search.brave.com/0SDHgntNqkUs6_HEwAXdQV5bOzfFQcGWKmsMn9tOGbA/rs:fit:500:0:1:0/g:ce/aHR0cHM6Ly93d3cu/ZGVzaWduc3R1ZGlv/MjEwLmNvbS93cC1j/b250ZW50L3VwbG9h/ZHMvMjAyMy8wOC9z/Y2FuZGluYXZpYW4t/bWluaW1hbGlzdGlj/LWludGVyaW9yLWRl/c2lnbi13aGl0ZS13/YWxscy5qcGVn",
        "source": "designstudio210.com",
        "favicon_url": "https://imgs.search.brave.com/DqZRilvlU3MYmYHsR5tefXjuqzok4RZ4N8rW2NCRRqs/rs:fit:32:32:1:0/g:ce/aHR0cDovL2Zhdmlj/b25zLnNlYXJjaC5i/cmF2ZS5jb20vaWNv/bnMvYTM2YWY4NWY3/ZjJlMjFkMDQxNTJk/YWViODc4ZDRlZjdk/MGIxMDE2Zjg1NzYy/YjlhMTI1ODgyMzE5/M2I1NjFkOC93d3cu/ZGVzaWduc3R1ZGlv/MjEwLmNvbS8"
      },
      {
        "title": "Scandinavian Minimalist Interior Design Style by PhotoUp",
        "source_page_url": "https://www.photoup.net/learn/what-is-scandinavian-minimalist-interior-design",
        "image_url": "https://cdn-wp.photoup.net/wp-content/uploads/2022/07/04143353/Scandinavian-Minimalist-Interior-Design-Style-by-PhotoUp-Livingroom.jpg",
        "thumbnail_url": "https://imgs.search.brave.com/FQjVd5Z1ZFk6Ni5H-7YmmlSlv-RoA0Yidl_Rx8Qf_5c/rs:fit:500:0:1:0/g:ce/aHR0cHM6Ly9jZG4t/d3AucGhvdG91cC5u/ZXQvd3AtY29udGVu/dC91cGxvYWRzLzIw/MjIvMDcvMDQxNDMz/NTMvU2NhbmRpbmF2/aWFuLU1pbmltYWxp/c3QtSW50ZXJpb3It/RGVzaWduLVN0eWxl/LWJ5LVBob3RvVXAt/TGl2aW5ncm9vbS5q/cGc",
        "source": "photoup.net",
        "favicon_url": "https://imgs.search.brave.com/3B2XU2zOOmyZebHbPmqYC6B6-c_KgoO7IYMFasecKfA/rs:fit:32:32:1:0/g:ce/aHR0cDovL2Zhdmlj/b25zLnNlYXJjaC5i/cmF2ZS5jb20vaWNv/bnMvMWJjMWVkNmM2/YWVlZjgwZjRlY2M1/NWMxMmQ1ODUzZTg3/NjIyMWE2ODI2MjNh/MGJhMjg5OWRhZWY0/OWEyNjQ0OS93d3cu/cGhvdG91cC5uZXQv"
      }
    ]
  },
  {
    "id": "store-example-images-search-3",
    "query": "Black and white film photography portraits",
    "query_translation_key": "settings.app_store_examples.images.search.3",
    "provider": "Brave Search",
    "status": "finished",
    "results": [
      {
        "title": "Atmospheric portrait of a female model shot with black and white film",
        "source_page_url": "https://expertphotography.com/shooting-on-black-and-white-film",
        "image_url": "https://expertphotography.com/img/2018/02/black-and-white-film-photography-tips.jpg",
        "thumbnail_url": "https://imgs.search.brave.com/APYLaiYD3AIINQs5SuLzjwQwFdnoxg1YCcNEMFYXNnI/rs:fit:500:0:1:0/g:ce/aHR0cHM6Ly9leHBl/cnRwaG90b2dyYXBo/eS5jb20vaW1nLzIw/MTgvMDIvYmxhY2st/YW5kLXdoaXRlLWZp/bG0tcGhvdG9ncmFw/aHktdGlwcy5qcGc",
        "source": "expertphotography.com",
        "favicon_url": "https://imgs.search.brave.com/e1tCgskyPFkWus5tgxYKVNgCTV4iEIxLEnOt3KtcBIk/rs:fit:32:32:1:0/g:ce/aHR0cDovL2Zhdmlj/b25zLnNlYXJjaC5i/cmF2ZS5jb20vaWNv/bnMvZDFmOGQ1NzJl/NTZhMWExNDYxY2Mw/N2Q0ZTk5Mzc1YTUw/NDk2YzBkYTJhYTA1/ODg5MzEwZDYxN2Ji/MjQxODg3MS9leHBl/cnRwaG90b2dyYXBo/eS5jb20v"
      },
      {
        "title": "Atmospheric portrait of a female model shot with black and white film",
        "source_page_url": "https://expertphotography.com/shooting-on-black-and-white-film",
        "image_url": "https://expertphotography.com/img/2018/02/black-and-white-film-photography-tips-5.jpg",
        "thumbnail_url": "https://imgs.search.brave.com/mAbgwhVpr_ujsmyxCmEBPR0bGF06JDU612maa7aRaHo/rs:fit:500:0:1:0/g:ce/aHR0cHM6Ly9leHBl/cnRwaG90b2dyYXBo/eS5jb20vaW1nLzIw/MTgvMDIvYmxhY2st/YW5kLXdoaXRlLWZp/bG0tcGhvdG9ncmFw/aHktdGlwcy01Lmpw/Zw",
        "source": "expertphotography.com",
        "favicon_url": "https://imgs.search.brave.com/e1tCgskyPFkWus5tgxYKVNgCTV4iEIxLEnOt3KtcBIk/rs:fit:32:32:1:0/g:ce/aHR0cDovL2Zhdmlj/b25zLnNlYXJjaC5i/cmF2ZS5jb20vaWNv/bnMvZDFmOGQ1NzJl/NTZhMWExNDYxY2Mw/N2Q0ZTk5Mzc1YTUw/NDk2YzBkYTJhYTA1/ODg5MzEwZDYxN2Ji/MjQxODg3MS9leHBl/cnRwaG90b2dyYXBo/eS5jb20v"
      },
      {
        "title": "Atmospheric portrait of a female model shot with black and white film",
        "source_page_url": "https://expertphotography.com/shooting-on-black-and-white-film",
        "image_url": "https://expertphotography.com/img/2018/02/black-and-white-film-photography-tips-2.jpg",
        "thumbnail_url": "https://imgs.search.brave.com/kcNtytGQf8eGGFwz1OYWmN9nG0S3qSo09wmkkCQdZ10/rs:fit:500:0:1:0/g:ce/aHR0cHM6Ly9leHBl/cnRwaG90b2dyYXBo/eS5jb20vaW1nLzIw/MTgvMDIvYmxhY2st/YW5kLXdoaXRlLWZp/bG0tcGhvdG9ncmFw/aHktdGlwcy0yLmpw/Zw",
        "source": "expertphotography.com",
        "favicon_url": "https://imgs.search.brave.com/e1tCgskyPFkWus5tgxYKVNgCTV4iEIxLEnOt3KtcBIk/rs:fit:32:32:1:0/g:ce/aHR0cDovL2Zhdmlj/b25zLnNlYXJjaC5i/cmF2ZS5jb20vaWNv/bnMvZDFmOGQ1NzJl/NTZhMWExNDYxY2Mw/N2Q0ZTk5Mzc1YTUw/NDk2YzBkYTJhYTA1/ODg5MzEwZDYxN2Ji/MjQxODg3MS9leHBl/cnRwaG90b2dyYXBo/eS5jb20v"
      },
      {
        "title": "A portrait of a man sitting in an outdoor cafe - tips for shooting with black and white film photography",
        "source_page_url": "https://expertphotography.com/shooting-on-black-and-white-film",
        "image_url": "https://expertphotography.com/img/2018/02/black-and-white-film-photography-tips-4.jpg",
        "thumbnail_url": "https://imgs.search.brave.com/ONqOSQaEtqHrwPUTXYU0AoCCkTc5eNKyZ6aV7OkNnt8/rs:fit:500:0:1:0/g:ce/aHR0cHM6Ly9leHBl/cnRwaG90b2dyYXBo/eS5jb20vaW1nLzIw/MTgvMDIvYmxhY2st/YW5kLXdoaXRlLWZp/bG0tcGhvdG9ncmFw/aHktdGlwcy00Lmpw/Zw",
        "source": "expertphotography.com",
        "favicon_url": "https://imgs.search.brave.com/e1tCgskyPFkWus5tgxYKVNgCTV4iEIxLEnOt3KtcBIk/rs:fit:32:32:1:0/g:ce/aHR0cDovL2Zhdmlj/b25zLnNlYXJjaC5i/cmF2ZS5jb20vaWNv/bnMvZDFmOGQ1NzJl/NTZhMWExNDYxY2Mw/N2Q0ZTk5Mzc1YTUw/NDk2YzBkYTJhYTA1/ODg5MzEwZDYxN2Ji/MjQxODg3MS9leHBl/cnRwaG90b2dyYXBo/eS5jb20v"
      }
    ]
  }
]

export default examples;
