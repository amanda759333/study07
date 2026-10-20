-- 작성일시: 2026-10-20 17:52 (KST)
--
-- 팀 편성 웹 앱의 DB 테이블 (Supabase PostgreSQL)
-- 공고 5장 「DB 최소 참고안」의 테이블 7개. 이름은 모두 tf_ 로 시작한다(공고 4.2, 6.3-13).
-- 6장 실습 테이블과 같은 DB(같은 Supabase 프로젝트)를 쓰므로 접두사로 구분한다.
-- Supabase의 SQL 편집기에 통째로 붙여 넣어 실행한다. 이미 있는 테이블은 건드리지 않는다(if not exists).
--
-- 제약 주석의 [공고 x.y]는 그 제약이 DB에서 지켜 주는 공고의 규칙이다.

-- 1. tf_students: 학생과 관리자 ---------------------------------------------

create table if not exists tf_students (
    id            bigint generated always as identity primary key,
    -- [공고 2.1] 학번으로 로그인하므로 학번 하나가 한 사람을 가리켜야 한다
    student_no    text    not null unique,
    name          text    not null,
    -- [공고 2.2] 역할은 6개: 기획자, 웹 프로그래머, 프론트엔드 디자이너, 테스터, 보고서 작성자, 발표자.
    --            명단 CSV의 주 역할이 6개 밖이면 저장되지 않는다.
    --            관리자(학번 admin)는 역할이 없으므로 null을 허용한다(check는 null을 통과시킴)
    main_role     text
        constraint tf_students_main_role_check
        check (main_role in ('기획자', '웹 프로그래머', '프론트엔드 디자이너',
                             '테스터', '보고서 작성자', '발표자')),
    -- [공고 3장 끝, 6.3-10] 비밀번호는 bcrypt 해시로 저장한다. 평문 열은 두지 않는다
    password_hash text    not null,
    is_admin      boolean not null default false
);

-- 2. tf_student_sub_roles: 보조 역할. 학생 1명에 0~2행 ----------------------
--    2행 이하([공고 2.2] 보조 역할 0~2개)는 앱이 명단을 올릴 때 검사한다

create table if not exists tf_student_sub_roles (
    student_id bigint not null references tf_students (id) on delete cascade,
    -- [공고 2.2] 보조 역할도 6개 역할 가운데 하나여야 한다
    role       text   not null
        constraint tf_student_sub_roles_role_check
        check (role in ('기획자', '웹 프로그래머', '프론트엔드 디자이너',
                        '테스터', '보고서 작성자', '발표자')),
    -- 같은 보조 역할이 한 학생에게 두 번 들어가지 않게 한다
    primary key (student_id, role)
);

-- 3. tf_teams: 팀 ------------------------------------------------------------

create table if not exists tf_teams (
    id   bigint generated always as identity primary key,
    -- [공고 2.3 「팀」] 관리자가 넣은 팀 수만큼 팀1, 팀2, … 를 만든다. 같은 이름의 팀이 둘이면 안 된다
    name text not null unique
);

-- 4. tf_members: 팀원 --------------------------------------------------------

create table if not exists tf_members (
    team_id    bigint   not null references tf_teams (id) on delete cascade,
    -- [공고 2.4 「팀이 꽉 참」, 5장] 팀의 자리는 1~4번뿐이다. 다섯 번째 자리를 막아
    --            4명인 팀에 한 명이 더 들어가지 못하게 한다(2.3 「인원」의 상한 4명)
    slot_no    smallint not null
        constraint tf_members_slot_no_check
        check (slot_no between 1 and 4),
    -- [공고 2.4 「이미 팀이 있음」, 2.5-4 검사 ②, 5장] 한 학생은 한 팀에만 소속된다.
    --            이미 팀이 있는 학생을 다른 팀에 넣으려 하면 저장되지 않는다
    student_id bigint   not null references tf_students (id) on delete cascade
        constraint tf_members_student_id_key unique,
    -- [공고 3장 「마지막 자리에 두 명이 동시에 들어감」, 5장] 한 팀의 같은 자리에는 한 명만 들어간다.
    --            빈 마지막 자리에 두 학생이 같은 순간 들어오면 먼저 도착한 학생만 기록되고
    --            나중 학생은 유일성 위반으로 실패한다.
    --            참고안대로 기본 키로 둔다(기본 키 = 유일성 + not null)
    constraint tf_members_pkey primary key (team_id, slot_no)
);

-- 5. tf_applications: 지원 ---------------------------------------------------
--    막힌 지원은 기록하지 않는다([공고 2.4 「막힌 지원」]). 접수된 지원만 대기 → 승인/거절로 바뀐다

create table if not exists tf_applications (
    id         bigint generated always as identity primary key,
    team_id    bigint      not null references tf_teams (id) on delete cascade,
    student_id bigint      not null references tf_students (id) on delete cascade,
    -- [공고 2.4] 접수된 지원의 상태는 대기, 승인, 거절 셋뿐이다
    status     text        not null default '대기'
        constraint tf_applications_status_check
        check (status in ('대기', '승인', '거절')),
    reason     text,                                -- 거절 이유 등
    created_at timestamptz not null default now()   -- UTC로 저장, 화면에서 KST로 바꿈([공고 4.4])
);

-- 6. tf_votes: 투표 ----------------------------------------------------------

create table if not exists tf_votes (
    application_id bigint not null references tf_applications (id) on delete cascade,
    voter_id       bigint not null references tf_students (id) on delete cascade,
    -- [공고 2.4] 투표는 찬성 또는 거부다
    vote           text   not null
        constraint tf_votes_vote_check
        check (vote in ('찬성', '거부')),
    -- [공고 2.4 「투표 바꾸기」] 한 사람은 한 지원에 한 번만 투표한다.
    --            두 번째 투표 행은 저장되지 않는다(투표를 바꾸지 못함)
    constraint tf_votes_pkey primary key (application_id, voter_id)
);

-- 7. tf_settings: 마감 여부 등 -----------------------------------------------

create table if not exists tf_settings (
    key   text primary key,
    value text not null
);

-- [공고 2.5-1] 마감 여부. 'true'가 되면 지원과 투표를 받지 않는다
insert into tf_settings (key, value) values ('closed', 'false')
on conflict (key) do nothing;

-- 행 수준 보안 --------------------------------------------------------------

-- Supabase는 public 스키마의 테이블을 Data API(anon 키)로도 열어 둔다.
-- 앱은 DATABASE_URL(postgres 역할)로 직접 접속하므로 RLS의 영향을 받지 않는다.
-- 정책 없이 RLS만 켜서 Data API로는 아무것도 읽고 쓸 수 없게 한다(비밀번호 해시 보호).
alter table tf_students          enable row level security;
alter table tf_student_sub_roles enable row level security;
alter table tf_teams             enable row level security;
alter table tf_members           enable row level security;
alter table tf_applications      enable row level security;
alter table tf_votes             enable row level security;
alter table tf_settings          enable row level security;
