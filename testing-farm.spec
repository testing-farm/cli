Name:           testing-farm
Version:        0.0.0
Release:        %autorelease
Summary:        Testing Farm CLI

License:        Apache-2.0
URL:            https://gitlab.com/testing-farm/cli
Source0:        %{pypi_source tft_cli}

BuildArch:      noarch
BuildRequires:  python3-devel

%description
CLI tool for interacting with the Testing Farm API.

%prep
%autosetup -n tft_cli-%{version}

%generate_buildrequires
%pyproject_buildrequires

%build
%pyproject_wheel

%install
%pyproject_install
%pyproject_save_files tft

%check
%pyproject_check_import

%files -n testing-farm -f %{pyproject_files}
#%doc README.adoc  # it's not in pypi source archive
%{_bindir}/testing-farm
